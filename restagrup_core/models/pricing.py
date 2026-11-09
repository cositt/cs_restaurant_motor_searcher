# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.tools.misc import formatLang

MARGIN_PARAM = 'restagrup.default_margin_percent'
DEFAULT_MARGIN_PERCENT = 20.0
FOREIGN_MARGIN_PARAM = 'restagrup.foreign_margin_percent'
DEFAULT_FOREIGN_MARGIN_PERCENT = 25.0  # restaurantes de fuera de España, cobren en la moneda que cobren
TEAM_LANG = 'es_ES'  # idioma de los textos internos (chatter, avisos), corra quien corra el proceso


class RestagrupPricing(models.AbstractModel):
    """Regla de negocio única: Restagrup vende al cliente el precio del restaurante
    más un margen (20 % por defecto, ajustable en Ajustes → Restagrup)."""
    _name = 'restagrup.pricing'
    _description = 'Cálculo del precio al cliente (precio del restaurante + margen)'

    @api.model
    def _percent_param(self, param, default):
        raw = self.env['ir.config_parameter'].sudo().get_param(param)
        if raw in (False, None, ''):
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    @api.model
    def margin_percent(self):
        return self._percent_param(MARGIN_PARAM, DEFAULT_MARGIN_PERCENT)

    @api.model
    def foreign_margin_percent(self):
        """Margen de los restaurantes de fuera de España (25 % por defecto, como en el CRM de Restagrup)."""
        return self._percent_param(FOREIGN_MARGIN_PARAM, DEFAULT_FOREIGN_MARGIN_PERCENT)

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
