# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

COURSES = [
    ('entrante', 'Entrante'),
    ('principal', 'Principal'),
    ('postre', 'Postre'),
    ('bebida', 'Bebida'),
    ('otro', 'Otro'),
]
MENU_TYPES = [
    ('almuerzo', 'Almuerzo'),
    ('buffet', 'Buffet'),
    ('cena', 'Cena'),
    ('desayuno', 'Desayuno'),
    ('picnic', 'Picnic'),
    ('show', 'Show'),
    ('sin_definir', 'Sin definir'),
]
COURSE_LABELS = dict(COURSES)
COURSE_ORDER = {key: index for index, (key, _label) in enumerate(COURSES)}


class RestaurantMenu(models.Model):
    _name = 'restagrup.restaurant.menu'
    _description = 'Menú de restaurante'
    _order = 'partner_id, sequence, id'

    name = fields.Char(string='Nombre del menú', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Restaurante', required=True, index=True, ondelete='cascade',
        domain=[('is_restaurant', '=', True)],
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(
        'res.currency', string='Moneda', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    partner_city = fields.Char(related='partner_id.city', string='Población')
    season = fields.Integer(
        string='Temporada', required=True, index=True,
        default=lambda self: fields.Date.context_today(self).year,
        help='Año de la temporada del menú (2025, 2026…). Sirve para no ofrecer menús antiguos: se filtra por'
             ' población y temporada, como «Sevilla 25» en el CRM actual.',
    )
    menu_type = fields.Selection(MENU_TYPES, string='Tipo de menú', default='sin_definir', required=True)
    cost_price = fields.Monetary(
        string='Precio coste', currency_field='currency_id',
        help='Lo que cobra el restaurante por persona.',
    )
    sale_price = fields.Monetary(
        string='Precio venta', currency_field='currency_id', compute='_compute_sale_price', store=True,
        readonly=False, help='Precio por persona al cliente. Sale solo del coste y el margen del restaurante,'
                             ' pero se puede escribir el que se quiera.',
    )
    profit_percent = fields.Float(
        string='% beneficio', compute='_compute_profit_percent', digits=(16, 2),
        help='Beneficio sobre el coste con los precios actuales.',
    )
    min_pax = fields.Integer(string='Mínimo de comensales')
    max_pax = fields.Integer(string='Capacidad (máx. comensales)')
    drinks_included = fields.Boolean(string='Bebidas incluidas')
    drinks_description = fields.Char(string='Bebidas')
    description = fields.Text(
        string='Descripción (texto)',
        help='El menú tal cual lo envía el restaurante. Si se rellena, es lo que sale en propuestas y documentos;'
             ' si no, salen los platos de abajo.',
    )
    notes = fields.Text(string='Observaciones')
    line_ids = fields.One2many('restagrup.restaurant.menu.line', 'menu_id', string='Platos', copy=True)
    display_text = fields.Text(string='Texto del menú', compute='_compute_display_text')

    @api.constrains('partner_id')
    def _check_partner_is_restaurant(self):
        for menu in self:
            if not menu.partner_id.is_restaurant:
                raise ValidationError(_('"%s" no está marcado como restaurante.', menu.partner_id.display_name))

    @api.depends('cost_price', 'partner_id.restaurant_margin_custom', 'partner_id.restaurant_margin_percent')
    def _compute_sale_price(self):
        pricing = self.env['restagrup.pricing']
        for menu in self:
            menu.sale_price = round(pricing.apply_margin(menu.cost_price, partner=menu.partner_id), 2)

    @api.depends('cost_price', 'sale_price')
    def _compute_profit_percent(self):
        for menu in self:
            menu.profit_percent = (
                round((menu.sale_price - menu.cost_price) / menu.cost_price * 100, 2) if menu.cost_price else 0.0
            )

    @api.constrains('season')
    def _check_season(self):
        for menu in self:
            if not 2000 <= menu.season <= 2100:
                raise ValidationError(_('La temporada es el año completo (por ejemplo 2026), no su abreviatura.'))

    @api.constrains('cost_price', 'sale_price')
    def _check_price(self):
        for menu in self:
            if menu.cost_price < 0 or menu.sale_price < 0:
                raise ValidationError(_('Los precios no pueden ser negativos.'))

    @api.constrains('min_pax', 'max_pax')
    def _check_pax(self):
        for menu in self:
            if menu.min_pax and menu.max_pax and menu.min_pax > menu.max_pax:
                raise ValidationError(_('El mínimo de comensales no puede superar al máximo.'))

    @api.depends(
        'name', 'sale_price', 'currency_id', 'drinks_included', 'drinks_description', 'notes', 'description',
        'line_ids.course', 'line_ids.name', 'line_ids.allergens', 'line_ids.sequence',
    )
    def _compute_display_text(self):
        for menu in self:
            menu.display_text = menu._render_text()

    def _render_text(self, with_price=True):
        """Texto plano del menú. Lleva el precio de VENTA (nunca el coste del restaurante). `with_price=False`
        para las propuestas, donde el precio lo pone la propia comparativa."""
        self.ensure_one()
        header = menu_name = self.name or ''
        if with_price and self.sale_price:
            header = _('%(name)s — %(price).2f %(symbol)s por persona', name=menu_name,
                       price=self.sale_price, symbol=self.currency_id.symbol or '')
        parts = [header]
        description = (self.description or '').strip()
        if description:
            parts.append(description)
        lines = [] if description else sorted(self.line_ids, key=lambda l: (COURSE_ORDER.get(l.course, len(COURSE_ORDER)), l.sequence, l.id))
        current = None
        for line in lines:
            if line.course != current:
                current = line.course
                parts.append('%s:' % COURSE_LABELS.get(current, current))
            dish = '- %s' % line.name
            if line.allergens:
                dish += _(' (alérgenos: %s)', line.allergens)
            parts.append(dish)
        # Con descripción en texto, las bebidas ya suelen venir en ella: solo se añaden si se detallaron aparte.
        if self.drinks_description or (self.drinks_included and not description):
            parts.append(_('Bebidas: %s', self.drinks_description or _('incluidas')))
        if self.notes:
            parts.append(self.notes)
        return '\n'.join(parts)


class RestaurantMenuLine(models.Model):
    _name = 'restagrup.restaurant.menu.line'
    _description = 'Plato de un menú de restaurante'
    _order = 'course_rank, sequence, id'

    menu_id = fields.Many2one('restagrup.restaurant.menu', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    course = fields.Selection(COURSES, string='Tipo', required=True, default='principal')
    name = fields.Char(string='Plato', required=True)
    allergens = fields.Char(string='Alérgenos')
    course_rank = fields.Integer(compute='_compute_course_rank', store=True)

    @api.depends('course')
    def _compute_course_rank(self):
        for line in self:
            line.course_rank = COURSE_ORDER.get(line.course, len(COURSE_ORDER))
