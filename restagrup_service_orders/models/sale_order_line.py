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
    service_meal = fields.Selection(
        selection=[('lunch', 'Comida'), ('dinner', 'Cena')],
        string='Comida/Cena',
    )
    restagrup_search_line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Búsqueda de restaurante origen',
        readonly=True, copy=False, index=True,
        help='Resultado del buscador de restaurantes (con su presupuesto) del que se'
             ' generó esta línea -- trazabilidad búsqueda → presupuesto → venta.',
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
            return self.env['restagrup.pricing'].apply_margin(product.standard_price)
        return super()._get_display_price()
