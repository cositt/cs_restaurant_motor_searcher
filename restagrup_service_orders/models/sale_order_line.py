# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    restaurant_id = fields.Many2one(
        'res.partner', string='Restaurante',
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
