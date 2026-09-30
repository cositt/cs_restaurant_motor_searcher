# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    restaurant_id = fields.Many2one(
        'res.partner', string='Restaurante', index=True,
        domain=[('is_restaurant', '=', True)],
        help='Si se rellena, este producto es un menú de ese restaurante: al añadirlo a'
             ' un presupuesto, la línea toma sola el restaurante y genera su hoja de servicio.'
             ' El precio de venta es el precio del producto, sin margen añadido.',
    )

    @api.constrains('restaurant_id')
    def _check_restaurant_is_restaurant(self):
        for product in self:
            if product.restaurant_id and not product.restaurant_id.is_restaurant:
                raise ValidationError(_(
                    '"%s" no está marcado como restaurante, no se le pueden asignar menús.'
                ) % product.restaurant_id.name)
