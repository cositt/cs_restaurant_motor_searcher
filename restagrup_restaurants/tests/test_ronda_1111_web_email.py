# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11 (lo que se habló con Gerard): un restaurante de Google no trae email, pero muchos lo
publican en su web. Al pedir presupuesto se busca: Google da la web (Place Details) y el email se saca de la página o
de su página de contacto. Si no hay, se avisa como antes."""
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

REQUESTS_GET = 'odoo.addons.restagrup_restaurants.models.web_email.requests.get'
DETAILS = 'https://maps.googleapis.com/maps/api/place/details/json'


def _response(url, json_data=None, text=''):
    response = MagicMock()
    response.url = url
    response.json.return_value = json_data or {}
    response.text = text
    response.headers = {'Content-Type': 'text/html; charset=utf-8'}
    response.raise_for_status.return_value = None
    return response


def fake_web(pages, website='https://www.flordesal.example/'):
    def get(url, params=None, **_kwargs):
        if url == DETAILS:
            return _response(url, {'status': 'OK', 'result': {'website': website}})
        return _response(url, text=pages.get(url, ''))
    return get


@tagged('post_install', '-at_install')
class TestRonda1111WebEmail(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.google_places_api_key', 'test-key')
        lead = cls.env['crm.lead'].create({'name': 'Grupo web'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 42})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'google', 'name': 'Flor De Sal Web', 'google_place_id': 'abc',
            'etiqueta': 'interesado'})

    def test_email_on_the_home_page(self):
        pages = {'https://www.flordesal.example/': '<a href="mailto:reservas@flordesal.example">Escríbenos</a>'}
        with patch(REQUESTS_GET, side_effect=fake_web(pages)):
            self.assertEqual(self.line._restagrup_find_web_email(), 'reservas@flordesal.example')
        self.assertEqual(self.line.email, 'reservas@flordesal.example')

    def test_email_on_the_contact_page(self):
        pages = {
            'https://www.flordesal.example/': '<a href="/contacto">Contacto</a><img src="logo@2x.png">',
            'https://www.flordesal.example/contacto': '<p>Grupos: grupos@flordesal.example</p>',
        }
        with patch(REQUESTS_GET, side_effect=fake_web(pages)):
            self.assertEqual(self.line._restagrup_find_web_email(), 'grupos@flordesal.example')

    def test_prefers_the_restaurant_domain_over_other_emails(self):
        pages = {'https://www.flordesal.example/':
                 'web hecha por soporte@agenciaweb.example — info@flordesal.example'}
        with patch(REQUESTS_GET, side_effect=fake_web(pages)):
            self.assertEqual(self.line._restagrup_find_web_email(), 'info@flordesal.example')

    def test_ignores_image_names_and_tracking_addresses(self):
        pages = {'https://www.flordesal.example/': 'logo@2x.png 1a2b@sentry.wixpress.com'}
        with patch(REQUESTS_GET, side_effect=fake_web(pages)):
            self.assertFalse(self.line._restagrup_find_web_email())

    def test_bulk_request_uses_the_email_from_the_web(self):
        pages = {'https://www.flordesal.example/': 'reservas@flordesal.example'}
        with patch(REQUESTS_GET, side_effect=fake_web(pages)):
            self.search.action_request_quote_interested()
        self.assertEqual(self.line.etiqueta, 'solicitado')
        self.assertTrue(any('su web' in (m.body or '') for m in self.search.message_ids))

    def test_without_web_email_it_still_says_so(self):
        with patch(REQUESTS_GET, side_effect=fake_web({}, website='')):
            with self.assertRaises(UserError):
                self.search.action_request_quote_interested()
