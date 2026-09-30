# -*- coding: utf-8 -*-
from odoo import api, models

MARGIN_PARAM = 'restagrup.default_margin_percent'
DEFAULT_MARGIN_PERCENT = 20.0


class RestagrupPricing(models.AbstractModel):
    """Regla de negocio única: Restagrup vende al cliente el precio del restaurante
    más un margen (20 % por defecto, ajustable en Ajustes → Restagrup)."""
    _name = 'restagrup.pricing'
    _description = 'Cálculo del precio al cliente (precio del restaurante + margen)'

    @api.model
    def margin_percent(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(MARGIN_PARAM)
        if raw in (False, None, ''):
            return DEFAULT_MARGIN_PERCENT
        try:
            return float(raw)
        except ValueError:
            return DEFAULT_MARGIN_PERCENT

    @api.model
    def apply_margin(self, restaurant_price):
        return restaurant_price * (1 + self.margin_percent() / 100)
