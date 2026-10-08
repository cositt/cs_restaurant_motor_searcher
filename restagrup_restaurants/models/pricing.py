# -*- coding: utf-8 -*-
from odoo import api, models


class RestagrupPricing(models.AbstractModel):
    """Margen por restaurante: si el restaurante tiene margen propio manda ese; si no, el general de Ajustes."""
    _inherit = 'restagrup.pricing'

    @api.model
    def margin_percent(self, partner=None):
        if partner and partner.restaurant_margin_custom:
            return partner.restaurant_margin_percent
        return super().margin_percent()

    @api.model
    def apply_margin(self, restaurant_price, percent=None, partner=None):
        """percent explícito (p.ej. margen ya congelado en una línea) > margen del restaurante > general."""
        if percent is None and partner:
            percent = self.margin_percent(partner=partner)
        return super().apply_margin(restaurant_price, percent=percent)
