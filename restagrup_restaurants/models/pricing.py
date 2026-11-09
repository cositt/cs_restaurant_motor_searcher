# -*- coding: utf-8 -*-
from odoo import api, models

HOME_COUNTRY_CODE = 'ES'


class RestagrupPricing(models.AbstractModel):
    """Margen por restaurante: el propio de su ficha si lo tiene; si no, el de fuera de España (25 %) para los
    restaurantes de otro país, cobren en la moneda que cobren; y si no, el general de Ajustes."""
    _inherit = 'restagrup.pricing'

    @api.model
    def _is_foreign_restaurant(self, partner):
        """Sin país se da por español: es lo habitual y así un dato sin rellenar no sube el precio."""
        country = partner.commercial_partner_id.country_id
        home = self.env.company.country_id.code or HOME_COUNTRY_CODE
        return bool(country) and country.code != home

    @api.model
    def margin_percent(self, partner=None):
        if partner and partner.restaurant_margin_custom:
            return partner.restaurant_margin_percent
        if partner and self._is_foreign_restaurant(partner):
            return self.foreign_margin_percent()
        return super().margin_percent()

    @api.model
    def apply_margin(self, restaurant_price, percent=None, partner=None):
        """percent explícito (p.ej. margen ya congelado en una línea) > margen del restaurante > general."""
        if percent is None and partner:
            percent = self.margin_percent(partner=partner)
        return super().apply_margin(restaurant_price, percent=percent)
