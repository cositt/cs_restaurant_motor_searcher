# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    restaurant_id = fields.Many2one(
        'res.partner', string='Restaurante',
        compute='_compute_restaurant_id', store=True, readonly=False, precompute=True,
        domain=[('is_restaurant', '=', True)],
        help='Restaurante que da este servicio. Al confirmar el presupuesto, las líneas se'
             ' agrupan por restaurante para generar su hoja de servicio.',
    )
    service_date = fields.Date(string='Fecha de servicio')
    service_hour = fields.Float(
        string='Hora', help='Hora del servicio (p. ej. 13:30). Viaja a la hoja de servicio del restaurante; '
                            'si cambia, «Reenviar cambios» lo detecta.',
    )
    service_meal = fields.Selection(
        selection=[('lunch', 'Comida'), ('dinner', 'Cena')],
        string='Comida/Cena',
    )
    service_event_type_id = fields.Many2one(
        'restagrup.event.type', string='Tipo de evento', ondelete='restrict',
        help='Desayuno, comida, cena… Sustituye al antiguo "Comida/Cena" (service_meal, que se conserva'
             ' en la base de datos sin uso).',
    )
    restagrup_search_line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Búsqueda de restaurante origen',
        readonly=True, copy=False, index=True,
        help='Resultado del buscador de restaurantes (con su presupuesto) del que se'
             ' generó esta línea -- trazabilidad búsqueda → presupuesto → venta.',
    )

    restagrup_unit_cost = fields.Float(
        string='Coste restaurante (€)', compute='_compute_restagrup_cost', store=True,
        readonly=False, precompute=True, digits='Product Price',
        help='Lo que cobra el restaurante por unidad (coste del menú, o el importe de su presupuesto).'
             ' Es de uso interno: nunca sale en el presupuesto del cliente.',
    )
    restagrup_margin_pct = fields.Float(
        string='Margen aplicado (%)', compute='_compute_restagrup_cost', store=True,
        readonly=False, precompute=True, digits=(16, 2),
        help='Margen de Restagrup con el que se calculó esta línea. Queda congelado: cambiar el margen'
             ' en Ajustes no toca las líneas ya creadas.',
    )
    restagrup_margin_amount = fields.Float(
        string='Margen (€)', compute='_compute_restagrup_margin_amount', digits='Product Price',
        help='Importe de la línea sin impuestos menos el coste del restaurante.',
    )

    @api.depends('product_id', 'restagrup_search_line_id')
    def _compute_restagrup_cost(self):
        pricing = self.env['restagrup.pricing']
        for line in self:
            product = line.product_id
            if product.restaurant_id and product.standard_price:
                cost = product.standard_price
            else:
                cost = line.restagrup_search_line_id.quote_amount
            line.restagrup_unit_cost = cost or 0.0
            partner = product.restaurant_id or line.restagrup_search_line_id.partner_id
            line.restagrup_margin_pct = pricing.margin_percent(partner=partner) if cost else 0.0

    @api.depends('price_unit', 'discount', 'product_uom_qty', 'restagrup_unit_cost')
    def _compute_restagrup_margin_amount(self):
        """Comisión de Restagrup = lo que se cobra menos lo que cobra el restaurante, los dos con el IVA incluido
        (así trabajan: 1.745 € de venta - 1.500 € del restaurante = 245 €). Se calcula sobre precio × cantidad, no
        sobre el subtotal sin impuestos, para que no cambie según el impuesto esté incluido o se sume por encima."""
        for line in self:
            charged = line.price_unit * line.product_uom_qty * (1 - (line.discount or 0.0) / 100.0)
            line.restagrup_margin_amount = (
                charged - line.restagrup_unit_cost * line.product_uom_qty if line.restagrup_unit_cost else 0.0
            )

    @api.depends('product_id')
    def _compute_restaurant_id(self):
        """Un menú (producto con restaurante) rellena solo el restaurante de la línea.
        Si el producto no es un menú se respeta lo que hubiera, para no borrar una
        asignación manual."""
        for line in self:
            menu_restaurant = line.product_id.restaurant_id
            if menu_restaurant:
                line.restaurant_id = menu_restaurant
            elif not line.restaurant_id:
                line.restaurant_id = False

    def _get_display_price(self):
        """Un menú de restaurante se vende al precio del restaurante (su coste) más el margen de
        Restagrup, no a una tarifa propia. Sin coste cargado se usa el precio de tarifa."""
        self.ensure_one()
        product = self.product_id
        if product.restaurant_id and product.standard_price:
            frozen = self.restagrup_margin_pct if self.restagrup_unit_cost else None
            return self.env['restagrup.pricing'].apply_margin(
                product.standard_price, percent=frozen, partner=product.restaurant_id)
        if self.restagrup_search_line_id and self.restagrup_unit_cost:
            # Línea nacida de un presupuesto de restaurante: el producto «servicio» no tiene precio de tarifa. Al
            # cambiar los comensales Odoo recalcula el precio; sin esto se quedaba en 0. Se mantiene coste + margen.
            return self.env['restagrup.pricing'].apply_margin(
                self.restagrup_unit_cost, percent=self.restagrup_margin_pct, partner=self.restaurant_id)
        return super()._get_display_price()

    @api.model
    def _restagrup_fill_event_type_from_meal(self):
        """Migración: el antiguo "Comida/Cena" pasa al tipo de evento nuevo. No pisa un tipo ya elegido."""
        mapping = {
            'lunch': 'restagrup_core.event_type_lunch',
            'dinner': 'restagrup_core.event_type_dinner',
        }
        for meal, xmlid in mapping.items():
            event_type = self.env.ref(xmlid, raise_if_not_found=False)
            if not event_type:
                continue
            lines = self.sudo().with_context(active_test=False).search([
                ('service_meal', '=', meal), ('service_event_type_id', '=', False),
            ])
            lines.write({'service_event_type_id': event_type.id})
