# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    restaurant_purchase_order_ids = fields.One2many(
        'purchase.order', 'partner_id', string='Hojas de servicio (pedidos de compra)',
    )
    menu_ids = fields.One2many(
        'product.template', 'restaurant_id', string='Menús',
        help='Menús de este restaurante: productos de servicio con su precio de venta.',
    )
    restaurant_worked_with = fields.Boolean(
        string='Ya hemos trabajado con este restaurante', compute='_compute_restaurant_worked_with',
        help='Se marca solo cuando existe al menos una hoja de servicio real (pedido'
             ' de compra) con este restaurante -- nunca solo por haberlo elegido.',
    )

    @api.depends('restaurant_purchase_order_ids.state')
    def _compute_restaurant_worked_with(self):
        for partner in self:
            partner.restaurant_worked_with = bool(
                partner.restaurant_purchase_order_ids.filtered(lambda po: po.state != 'cancel')
            )
