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


# Provincia por las dos primeras cifras del código postal (códigos de provincia del INE -> res.country.state).
ZIP_PREFIX_STATE = {
    '01': 'VI', '02': 'AB', '03': 'A', '04': 'AL', '05': 'AV', '06': 'BA', '07': 'PM', '08': 'B', '09': 'BU',
    '10': 'CC', '11': 'CA', '12': 'CS', '13': 'CR', '14': 'CO', '15': 'C', '16': 'CU', '17': 'GI', '18': 'GR',
    '19': 'GU', '20': 'SS', '21': 'H', '22': 'HU', '23': 'J', '24': 'LE', '25': 'L', '26': 'LO', '27': 'LU',
    '28': 'M', '29': 'MA', '30': 'MU', '31': 'NA', '32': 'OR', '33': 'O', '34': 'P', '35': 'GC', '36': 'PO',
    '37': 'SA', '38': 'TF', '39': 'S', '40': 'SG', '41': 'SE', '42': 'SO', '43': 'T', '44': 'TE', '45': 'TO',
    '46': 'V', '47': 'VA', '48': 'BI', '49': 'ZA', '50': 'Z', '51': 'CE', '52': 'ME',
}


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
        return self._restagrup_split_address_vals(vals)

    @api.model
    def _restagrup_split_address_vals(self, vals):
        """Separa «calle, CP ciudad» de vals['street'] en calle, CP, ciudad, provincia y país (España). La ciudad
        de la dirección manda sobre la que viniera en vals. Sin CP y ciudad al final, vals tal cual."""
        parts = split_pasted_address(vals.get('street'))
        if not parts:
            return vals
        street, zip_code, city = parts
        new_vals = dict(vals, street=street, city=city)
        new_vals.setdefault('zip', zip_code)
        if not vals.get('country_id'):
            new_vals['country_id'] = self.env.ref('base.es').id
        if not vals.get('state_id') and new_vals['country_id'] == self.env.ref('base.es').id:
            state = self._restagrup_state_from_zip(new_vals['zip'])
            if state:
                new_vals['state_id'] = state.id
        return new_vals

    @api.model
    def _restagrup_state_from_zip(self, zip_code):
        code = ZIP_PREFIX_STATE.get((zip_code or '')[:2])
        if not code:
            return self.env['res.country.state']
        return self.env['res.country.state'].search(
            [('country_id', '=', self.env.ref('base.es').id), ('code', '=', code)], limit=1)

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
