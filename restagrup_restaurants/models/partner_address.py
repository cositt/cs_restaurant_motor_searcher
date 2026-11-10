# -*- coding: utf-8 -*-
"""Dirección pegada entera en «Calle» (ronda de ajustes 09/11).

Al copiar la dirección de Google Maps («C. Sta. María la Blanca, 34, Casco Antiguo, 41001 Sevilla») todo caía en
la calle y la ciudad quedaba vacía, así que el buscador (que filtra por ciudad) no encontraba el restaurante.
Si la ciudad está vacía y la calle acaba en «CP Ciudad», se separa sola. Lo que ya está separado no se toca."""
import re

from odoo import api, models

# «…, 41001 Sevilla» / «… 29005 Málaga, España» -> calle, CP (5 cifras), ciudad.
PASTED_ADDRESS = re.compile(
    r'^\s*(?P<street>.+?)[,\s]+(?P<zip>\d{5})\s+(?P<city>[^,\d][^,]*?)\s*(?:,\s*(?:España|Spain))?\s*$',
    re.IGNORECASE)


def split_pasted_address(street):
    """(calle, cp, ciudad) si la calle trae CP y ciudad al final; si no, None."""
    match = PASTED_ADDRESS.match(street or '')
    if not match:
        return None
    return match.group('street').strip(' ,'), match.group('zip'), match.group('city').strip()


class ResPartnerPastedAddress(models.Model):
    _inherit = 'res.partner'

    def _restagrup_address_vals(self, vals, current_city=False):
        if vals.get('city') or current_city or not vals.get('street'):
            return vals
        parts = split_pasted_address(vals['street'])
        if not parts:
            return vals
        street, zip_code, city = parts
        new_vals = dict(vals, street=street, city=city)
        new_vals.setdefault('zip', zip_code)
        if not vals.get('country_id'):
            new_vals['country_id'] = self.env.ref('base.es').id
        return new_vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._restagrup_address_vals(vals) for vals in vals_list])

    def write(self, vals):
        if not vals.get('street') or vals.get('city'):
            return super().write(vals)
        without_city = self.filtered(lambda partner: not partner.city)
        if not without_city or without_city != self:
            return super().write(vals)
        country = self[:1].country_id.id
        new_vals = self._restagrup_address_vals(dict(vals, country_id=vals.get('country_id') or country))
        if not new_vals.get('country_id'):
            new_vals.pop('country_id', None)
        return super().write(new_vals)
