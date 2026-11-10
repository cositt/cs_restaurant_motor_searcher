# -*- coding: utf-8 -*-
"""Fichas de restaurante más completas con menos trabajo (ronda de ajustes 09/11).

- «Completar desde Google»: busca el restaurante en Google Places (si no se conoce ya) y rellena lo que esté vacío:
  dirección separada, teléfono, web, valoración y posición. Lo escrito a mano no se toca. Es una llamada de pago por
  restaurante, así que solo se hace al pulsar el botón.
- Campaña de datos: a los restaurantes con los que se ha trabajado desde una fecha y con la ficha incompleta se les
  pide lo que falta con el correo de siempre (por la cola de aprobación; la respuesta la lee la IA)."""
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .restaurant_search import GOOGLE_PLACES_DETAILS_URL, GOOGLE_PLACES_TEXTSEARCH_URL

_logger = logging.getLogger(__name__)

DETAIL_FIELDS = ('place_id,formatted_phone_number,international_phone_number,website,rating,user_ratings_total,'
                 'geometry,address_components')
WORKED_ETIQUETAS = ('solicitado', 'presupuesto_recibido')
CAMPAIGN_SINCE = '2026-01-01'


def _component(components, kind):
    return next((c.get('long_name') for c in components if kind in (c.get('types') or [])), '')


class ResPartnerGoogleFill(models.Model):
    _inherit = 'res.partner'

    # --- completar desde Google ---

    def _restagrup_google_get(self, url, params):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            _logger.exception('Fallo consultando Google Places para %s', self.name)
            raise UserError(_('No se ha podido consultar Google ahora mismo. Inténtalo de nuevo en un rato.'))

    def _restagrup_google_place_id(self, api_key):
        if self.restaurant_google_place_id:
            return self.restaurant_google_place_id
        query = ' '.join(part for part in (self.name, self.street, self.city) if part)
        payload = self._restagrup_google_get(GOOGLE_PLACES_TEXTSEARCH_URL, {'query': query, 'key': api_key})
        results = payload.get('results') or []
        if payload.get('status') != 'OK' or not results:
            raise UserError(_('Google no encuentra «%s». Revisa el nombre y la ciudad y vuelve a probar.') % query)
        return results[0].get('place_id')

    def _restagrup_google_vals(self, result):
        """Lo que trae Google, solo para los campos vacíos de la ficha."""
        components = result.get('address_components') or []
        route, number = _component(components, 'route'), _component(components, 'street_number')
        location = (result.get('geometry') or {}).get('location') or {}
        found = {
            'street': ', '.join(part for part in (route, number) if part),
            'zip': _component(components, 'postal_code'),
            'city': _component(components, 'locality'),
            'phone': result.get('formatted_phone_number') or result.get('international_phone_number'),
            'website': result.get('website'),
            'restaurant_google_place_id': result.get('place_id'),
            'restaurant_google_rating': result.get('rating'),
            'restaurant_google_review_count': result.get('user_ratings_total'),
            'partner_latitude': location.get('lat'),
            'partner_longitude': location.get('lng'),
        }
        return {name: value for name, value in found.items() if value and not self[name]}

    def action_complete_from_google(self):
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('restagrup.google_places_api_key')
        if not api_key:
            raise UserError(_('Falta la clave de Google Places en Ajustes → Restagrup.'))
        place_id = self._restagrup_google_place_id(api_key)
        payload = self._restagrup_google_get(GOOGLE_PLACES_DETAILS_URL, {
            'place_id': place_id, 'fields': DETAIL_FIELDS, 'language': 'es', 'key': api_key})
        if payload.get('status') != 'OK':
            raise UserError(_('Google no ha devuelto los datos de «%s».') % self.name)
        vals = self._restagrup_google_vals(dict(payload.get('result') or {}, place_id=place_id))
        if vals.get('city') and not self.country_id:
            vals['country_id'] = self.env.ref('base.es').id
        if vals:
            self.write(vals)
        labels = [self._fields[name].string for name in vals if name in self._fields]
        self.message_post(body=_('Completado desde Google: %s.') % (', '.join(labels) or _('nada nuevo')))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success' if vals else 'info', 'title': _('Google'),
                       'message': _('Rellenado: %s.') % ', '.join(labels) if labels else _(
                           'La ficha ya tenía todo lo que da Google.'),
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    # --- campaña: pedir los datos que faltan ---

    @api.model
    def _restagrup_data_campaign_lines(self, since=CAMPAIGN_SINCE):
        """La última petición de cada restaurante con el que se ha trabajado desde `since` (pedido presupuesto o
        recibido), si su ficha está incompleta y tiene email."""
        lines = self.env['restagrup.restaurant.search.line'].search([
            ('partner_id', '!=', False), ('create_date', '>=', since),
            '|', ('etiqueta', 'in', WORKED_ETIQUETAS), ('quote_received_date', '!=', False),
        ], order='create_date desc, id desc')
        latest = {}
        for line in lines:
            partner = line.partner_id
            if partner.id in latest or not partner.restaurant_is_incomplete or not partner.email:
                continue
            latest[partner.id] = line
        return self.env['restagrup.restaurant.search.line'].browse([line.id for line in latest.values()])

    @api.model
    def _restagrup_data_campaign_targets(self, since=CAMPAIGN_SINCE):
        return self._restagrup_data_campaign_lines(since).partner_id

    @api.model
    def action_data_request_campaign(self):
        """Pide a cada restaurante de la campaña lo que le falta. No repite a quien ya se le pidió."""
        asked = 0
        for line in self._restagrup_data_campaign_lines():
            already = self.env['restagrup.pending.mail'].search_count([
                ('kind', '=', 'data_request'), ('line_id.partner_id', '=', line.partner_id.id)])
            if already or line.data_request_date:
                continue
            line.action_request_missing_data()
            asked += 1
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _('Pedir datos que faltan'),
                       'message': _('%s restaurantes: el correo está en «Pendientes de aprobar».') % asked
                       if asked else _('No hay restaurantes nuevos a los que pedir datos.')},
        }
