# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: fichas de restaurante más completas con menos trabajo.

- «Completar desde Google» en la ficha: dirección separada, teléfono, web, valoración y posición. Solo rellena lo
  que está vacío: lo escrito a mano no se toca.
- Campaña: a los restaurantes con los que se ha trabajado este año y con la ficha incompleta se les piden los datos
  que faltan (el mismo correo de siempre, por la cola de aprobación; su respuesta la lee la IA).
"""
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

REQUESTS_GET = 'odoo.addons.restagrup_restaurants.models.partner_google_fill.requests.get'
LINE = 'restagrup.restaurant.search.line'

TEXT_SEARCH = {'status': 'OK', 'results': [{'place_id': 'PLACE-ORO'}]}
DETAILS = {'status': 'OK', 'result': {
    'place_id': 'PLACE-ORO',
    'formatted_phone_number': '954 00 00 00',
    'website': 'https://3deoro.example',
    'rating': 4.6, 'user_ratings_total': 812,
    'geometry': {'location': {'lat': 37.386, 'lng': -5.99}},
    'address_components': [
        {'long_name': '34', 'types': ['street_number']},
        {'long_name': 'Calle Santa María la Blanca', 'types': ['route']},
        {'long_name': 'Sevilla', 'types': ['locality', 'political']},
        {'long_name': '41004', 'types': ['postal_code']},
    ],
}}


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@tagged('post_install', '-at_install')
class TestRonda0911GoogleFill(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.google_places_api_key', 'test-key')

    def _fill(self, partner):
        with patch(REQUESTS_GET, side_effect=[_response(TEXT_SEARCH), _response(DETAILS)]) as get:
            partner.action_complete_from_google()
        return get

    def test_fills_the_empty_data(self):
        partner = self.env['res.partner'].create({'name': 'El 3 de Oro', 'is_restaurant': True, 'city': 'Sevilla'})
        self._fill(partner)
        self.assertEqual(partner.street, 'Calle Santa María la Blanca, 34')
        self.assertEqual(partner.zip, '41004')
        self.assertEqual(partner.phone, '954 00 00 00')
        self.assertEqual(partner.website, 'https://3deoro.example')
        self.assertEqual(partner.restaurant_google_place_id, 'PLACE-ORO')
        self.assertEqual(partner.restaurant_google_review_count, 812)
        self.assertAlmostEqual(partner.partner_latitude, 37.386)

    def test_what_was_written_by_hand_is_kept(self):
        partner = self.env['res.partner'].create({
            'name': 'El 3 de Oro', 'is_restaurant': True, 'city': 'Sevilla', 'phone': '600 11 22 33'})
        self._fill(partner)
        self.assertEqual(partner.phone, '600 11 22 33')
        self.assertTrue(any('Google' in (m.body or '') for m in partner.message_ids))

    def test_with_a_known_place_it_goes_straight_to_details(self):
        partner = self.env['res.partner'].create({
            'name': 'El 3 de Oro', 'is_restaurant': True, 'restaurant_google_place_id': 'PLACE-ORO'})
        with patch(REQUESTS_GET, return_value=_response(DETAILS)) as get:
            partner.action_complete_from_google()
        self.assertEqual(get.call_count, 1)
        self.assertEqual(partner.city, 'Sevilla')

    def test_not_found_says_so(self):
        partner = self.env['res.partner'].create({'name': 'Nadie', 'is_restaurant': True})
        with patch(REQUESTS_GET, return_value=_response({'status': 'ZERO_RESULTS', 'results': []})):
            with self.assertRaises(UserError):
                partner.action_complete_from_google()

    def test_without_api_key_says_so(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.google_places_api_key', '')
        partner = self.env['res.partner'].create({'name': 'Sin clave', 'is_restaurant': True})
        with self.assertRaises(UserError):
            partner.action_complete_from_google()

    def test_restaurant_form_has_the_button(self):
        arch = self.env['res.partner'].get_view(self.env.ref('base.view_partner_form').id, 'form')['arch']
        self.assertIn('action_complete_from_google', arch)


@tagged('post_install', '-at_install')
class TestRonda0911DataCampaign(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lead = cls.env['crm.lead'].create({'name': 'Grupo 2026'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 20})

    def _restaurant(self, name, worked=True, complete=False, email='x@example.com'):
        vals = {'name': name, 'is_restaurant': True, 'email': email}
        if complete:
            vals.update(restaurant_closed_weekday='mon', restaurant_group_manager='Ana',
                        restaurant_group_mobile='600000000', restaurant_iban='ES9121000418450200051332')
        partner = self.env['res.partner'].create(vals)
        if worked:
            self.env[LINE].create({
                'search_id': self.search.id, 'source': 'partner', 'name': name, 'partner_id': partner.id,
                'etiqueta': 'solicitado'})
        return partner

    def test_campaign_asks_only_incomplete_restaurants_we_worked_with(self):
        asked = self._restaurant('Casa Falta')
        self._restaurant('Casa Completa', complete=True)
        self._restaurant('Casa Nunca', worked=False)
        self._restaurant('Casa Sin Email', email=False)
        targets = self.env['res.partner']._restagrup_data_campaign_targets('2026-01-01')
        self.assertIn(asked, targets)
        self.assertEqual(set(targets.mapped('name')) & {'Casa Completa', 'Casa Nunca', 'Casa Sin Email'}, set())

    def test_campaign_leaves_the_emails_in_the_approval_queue(self):
        asked = self._restaurant('Casa Cola')
        self.env['res.partner'].action_data_request_campaign()
        queued = self.env['restagrup.pending.mail'].search([
            ('kind', '=', 'data_request'), ('line_id.partner_id', '=', asked.id), ('state', '=', 'pending')])
        self.assertEqual(len(queued), 1)
        self.env['res.partner'].action_data_request_campaign()
        self.assertEqual(self.env['restagrup.pending.mail'].search_count([
            ('kind', '=', 'data_request'), ('line_id.partner_id', '=', asked.id)]), 1, 'No se repite.')
