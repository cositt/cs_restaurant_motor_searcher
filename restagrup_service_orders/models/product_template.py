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
             ' El "Coste" es lo que cobra el restaurante; el precio al cliente sale solo sumándole el margen',
    )

    @api.constrains('restaurant_id')
    def _check_restaurant_is_restaurant(self):
        for product in self:
            if product.restaurant_id and not product.restaurant_id.is_restaurant:
                raise ValidationError(_(
                    '"%s" no está marcado como restaurante, no se le pueden asignar menús.'
                ) % product.restaurant_id.name)

    restagrup_client_price = fields.Float(
        string='Precio al cliente (€)', compute='_compute_restagrup_client_price',
        digits='Product Price',
        help='Precio del restaurante + margen de Restagrup. Es el precio que se pone al cliente en'
             ' el presupuesto (solo para menús de restaurante).',
    )

    @api.depends('restaurant_id', 'standard_price', 'restaurant_id.restaurant_margin_custom',
                 'restaurant_id.restaurant_margin_percent')
    def _compute_restagrup_client_price(self):
        pricing = self.env['restagrup.pricing']
        for product in self:
            product.restagrup_client_price = (
                pricing.apply_margin(product.standard_price, partner=product.restaurant_id)
                if product.restaurant_id else 0.0
            )
