# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.tools.misc import formatLang

MARGIN_PARAM = 'restagrup.default_margin_percent'
DEFAULT_MARGIN_PERCENT = 20.0
TEAM_LANG = 'es_ES'  # idioma de los textos internos (chatter, avisos), corra quien corra el proceso


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
    def apply_margin(self, restaurant_price, percent=None):
        """percent: margen ya congelado en una línea; si no se indica, el vigente en Ajustes."""
        if percent is None:
            percent = self.margin_percent()
        return restaurant_price * (1 + percent / 100)

    @api.model
    def format_amount(self, amount):
        """«1.102,50»: importe para los textos del equipo, también desde el correo entrante (sin idioma de usuario)."""
        return formatLang(self.with_context(lang=TEAM_LANG).env, amount or 0.0, digits=2)
