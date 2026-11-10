# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang

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
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(
        'res.currency', string='Moneda', required=True, compute='_compute_currency_id', store=True,
        readonly=False, precompute=True, help='La del restaurante: el coste se apunta en lo que cobra él.',
    )
    company_currency_id = fields.Many2one(
        'res.currency', string='Moneda de venta', compute='_compute_company_currency_id')
    is_foreign_currency = fields.Boolean(string='Otra moneda', compute='_compute_company_currency_id')
    exchange_rate = fields.Float(
        string='Cambio (€ por unidad)', digits=(16, 6), copy=False,
        help='Lo que vale en euros 1 unidad de la moneda del restaurante, con el cambio del Banco Central Europeo'
             ' del día en que se pulsó «Convertir a euros».',
    )
    rate_date = fields.Date(string='Fecha del cambio', copy=False)
    cost_price_eur = fields.Monetary(
        string='Coste en euros', currency_field='company_currency_id', compute='_compute_cost_price_eur',
        store=True, help='El coste pasado a euros con el cambio guardado. Sin cambio, 0: hay que convertirlo.',
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
        string='Precio venta', currency_field='company_currency_id', compute='_compute_sale_price', store=True,
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

    @api.depends('partner_id.restaurant_currency_code')
    def _compute_currency_id(self):
        exchange = self.env['restagrup.exchange']
        for menu in self:
            menu.currency_id = exchange.currency_by_code(menu.partner_id.restaurant_currency_code or 'EUR')

    @api.depends('currency_id')
    def _compute_company_currency_id(self):
        company_currency = self.env.company.currency_id
        for menu in self:
            menu.company_currency_id = company_currency
            menu.is_foreign_currency = bool(menu.currency_id) and menu.currency_id != company_currency

    @api.depends('cost_price', 'currency_id', 'exchange_rate')
    def _compute_cost_price_eur(self):
        for menu in self:
            if menu.is_foreign_currency:
                menu.cost_price_eur = round(menu.cost_price * menu.exchange_rate, 2)
            else:
                menu.cost_price_eur = menu.cost_price

    @api.depends('cost_price_eur', 'partner_id.restaurant_margin_custom', 'partner_id.restaurant_margin_percent',
                 'partner_id.country_id')
    def _compute_sale_price(self):
        pricing = self.env['restagrup.pricing']
        for menu in self:
            menu.sale_price = round(pricing.apply_margin(menu.cost_price_eur, partner=menu.partner_id), 2)

    @api.depends('cost_price_eur', 'sale_price')
    def _compute_profit_percent(self):
        for menu in self:
            cost = menu.cost_price_eur
            menu.profit_percent = round((menu.sale_price - cost) / cost * 100, 2) if cost else 0.0

    def action_convert_to_eur(self):
        """«Convertir a euros», como en el CRM de Restagrup: cambio del día del BCE y precio de venta con el margen."""
        foreign = self.filtered('is_foreign_currency')
        if not foreign:
            return True
        exchange = self.env['restagrup.exchange']
        exchange.refresh_rates(foreign.currency_id)
        today = fields.Date.context_today(self)
        for menu in foreign:
            rate = exchange.eur_per_unit(menu.currency_id)
            if not rate:
                raise UserError(_('El Banco Central Europeo no publica el cambio de %s.', menu.currency_id.name))
            # Al cambiar el coste en euros se recalcula el precio de venta con el margen del restaurante.
            menu.write({'exchange_rate': rate, 'rate_date': today})
        return True

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
        'name', 'sale_price', 'drinks_included', 'drinks_description', 'notes', 'description',
        'line_ids.course', 'line_ids.name', 'line_ids.allergens', 'line_ids.sequence',
    )
    def _compute_display_text(self):
        for menu in self:
            menu.display_text = menu._render_text()

    def action_preview_dishes(self):
        """El «ojo»: nombre, precio y platos del menú en una ventana, sin salir de la lista."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.name, 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'new',
            'views': [(self.env.ref('restagrup_restaurants.view_restaurant_menu_preview_form').id, 'form')],
        }

    def _render_text_for_restaurant(self):
        """Texto del menú para escribir al propio restaurante: con su precio (el de coste), nunca el nuestro."""
        self.ensure_one()
        text = self._render_text(with_price=False)
        if self.cost_price:
            text += '\n' + _('Precio %(price)s %(symbol)s', price=formatLang(self.env, self.cost_price, digits=2),
                               symbol=self.currency_id.symbol or '')
        return text

    def _render_text(self, with_price=True):
        """Texto plano del menú. Lleva el precio de VENTA (nunca el coste del restaurante). `with_price=False`
        para las propuestas, donde el precio lo pone la propia comparativa."""
        self.ensure_one()
        header = menu_name = self.name or ''
        if with_price and self.sale_price:
            header = _('%(name)s — %(price)s %(symbol)s por persona', name=menu_name,
                       price=formatLang(self.env, self.sale_price, digits=2),
                       symbol=self.company_currency_id.symbol or '')
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
