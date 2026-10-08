# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RestaurantSearchLineComparison(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    menu_id = fields.Many2one(
        'restagrup.restaurant.menu', string='Menú ofrecido', copy=False, ondelete='set null',
        domain="[('partner_id', '=', partner_id)]",
        help='Menú del restaurante que acompaña a este presupuesto en la comparativa para el cliente.',
    )
    quote_client_price_per_person = fields.Float(
        string='Precio al cliente por persona (€)', compute='_compute_quote_client_price_per_person',
        digits=(16, 2),
        help='Precio al cliente (presupuesto + margen) dividido entre los comensales de la búsqueda.',
    )

    @api.depends('quote_amount', 'search_id.min_capacity')
    def _compute_quote_client_price_per_person(self):
        for line in self:
            pax = line.search_id.min_capacity
            line.quote_client_price_per_person = (
                round(line.quote_client_price / pax, 2) if pax and line.quote_client_price else 0.0
            )

    @api.constrains('menu_id', 'partner_id')
    def _check_menu_belongs_to_restaurant(self):
        for line in self:
            if line.menu_id and line.menu_id.partner_id != line.partner_id:
                raise ValidationError(_('El menú "%(menu)s" no pertenece a %(restaurant)s.',
                                        menu=line.menu_id.name, restaurant=line.name))


class RestaurantSearchComparison(models.Model):
    _inherit = 'restagrup.restaurant.search'

    restaurant_visible = fields.Boolean(
        string='Restaurante visible', default=True,
        help='Si está marcado, la agencia ve el nombre y la dirección del restaurante en la propuesta. Si no,'
             ' solo ve el menú y el precio (útil con clientes nuevos o que puedan saltarse la gestión).',
    )

    def restagrup_comparison_rows(self):
        """Filas de la comparativa para el cliente: un restaurante por fila, del más barato al más caro.

        Solo presupuestos confirmados (los que la IA propuso y nadie ha registrado todavía no salen) y solo
        precio al cliente por persona: ni el importe del restaurante, ni el margen, ni el total (el total llega
        con la confirmación de reserva). Con «Restaurante visible» desmarcado el restaurante se oculta."""
        self.ensure_one()
        lines = self.line_ids.filtered(
            lambda line: line.quote_amount and line.etiqueta == 'presupuesto_recibido'
        ).sorted(lambda line: (line.quote_amount, line.id))
        visible = self.restaurant_visible
        return [{
            'line': line,
            'name': line.name if visible else _('Opción %s', index),
            'partner': line.partner_id if visible else line.partner_id.browse(),
            'price_per_person': line.quote_client_price_per_person,
            'menu': line.menu_id,
            'menu_text': line.menu_id._render_text(with_price=False) if line.menu_id else '',
            'notes': line.quote_notes or '',
        } for index, line in enumerate(lines, start=1)]
