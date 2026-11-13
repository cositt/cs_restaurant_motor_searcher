# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestG1Reunion1211(TransactionCase):
    """Reunión 12/11, bloque G1: 7.2 bebida repetida, 3.5 dirección de Google troceada, 4.5 «+ IVA» y 4.6 aviso
    de que el restaurante ha contestado aunque no dé un precio único."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Line = cls.env['restagrup.restaurant.search.line']
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo G1'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'MADRID', 'min_capacity': 40})
        cls.restaurant = cls.Partner.create({'name': 'Casa G1', 'is_restaurant': True, 'email': 'g1@example.com'})

    # --- 7.2 -------------------------------------------------------------------------------------------------
    def _menu(self, drinks):
        return self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú Estudiantes 2027', 'partner_id': self.restaurant.id,
            'drinks_included': True, 'drinks_description': drinks,
            'line_ids': [
                (0, 0, {'course': 'entrante', 'name': 'Sopa de fideos'}),
                (0, 0, {'course': 'principal', 'name': 'Pollo'}),
                (0, 0, {'course': 'bebida', 'name': 'refresco'}),
                (0, 0, {'course': 'otro', 'name': 'Pan'}),
            ]})

    def test_drink_in_dishes_and_drinks_field_is_listed_once(self):
        menu = self._menu('refresco')
        included = '\n'.join(menu._always_included())
        self.assertEqual(included.lower().count('refresco'), 1, included)
        self.assertIn('Pan', included)
        text = menu._render_text(with_price=False)
        self.assertEqual(text.lower().count('refresco'), 1, text)

    def test_drink_already_in_a_longer_drinks_text_is_listed_once(self):
        menu = self._menu('agua, vino o refresco')
        text = menu._render_text(with_price=False)
        self.assertEqual(text.lower().count('refresco'), 1, text)
        self.assertIn('agua, vino o refresco', text)

    def test_drink_not_in_drinks_text_is_kept(self):
        menu = self._menu('agua')
        included = '\n'.join(menu._always_included())
        self.assertIn('refresco', included)
        self.assertIn('agua', included)

    # --- 3.5 -------------------------------------------------------------------------------------------------
    def test_add_as_contact_splits_the_google_address(self):
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'RIBS ABADA',
            'address': 'C. de Atocha, 11, 28012 Madrid, España', 'phone': '910000000'})
        line.action_add_as_partner()
        partner = line.partner_id
        self.assertEqual(partner.street, 'C. de Atocha, 11')
        self.assertEqual(partner.zip, '28012')
        self.assertEqual(partner.city, 'Madrid')
        self.assertEqual(partner.state_id, self.env.ref('base.state_es_m'))
        self.assertEqual(partner.country_id, self.env.ref('base.es'))

    def test_add_as_contact_keeps_search_city_when_address_cannot_be_split(self):
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Sin CP', 'address': 'Plaza Mayor',
            'phone': '910000001'})
        line.action_add_as_partner()
        self.assertEqual(line.partner_id.street, 'Plaza Mayor')
        self.assertEqual(line.partner_id.city, 'MADRID')

    def test_pasted_address_also_gets_the_province(self):
        partner = self.Partner.create({'name': 'Pegada', 'street': 'C. Sta. María la Blanca, 34, 41001 Sevilla'})
        self.assertEqual(partner.city, 'Sevilla')
        self.assertEqual(partner.state_id, self.env.ref('base.state_es_se'))

    # --- 4.5 / 4.6 -------------------------------------------------------------------------------------------
    def _requested_line(self):
        return self.Line.create({
            'search_id': self.search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'email': self.restaurant.email, 'etiqueta': 'solicitado'})

    def _reply(self, line, data):
        with patch(LLM_PATH, return_value=(data, 'groq')):
            line.message_update({'body': '<p>Os paso el precio.</p>'})

    def test_price_without_vat_gets_ten_percent_added(self):
        line = self._requested_line()
        self._reply(line, {'precio_persona': 20, 'iva_incluido': False})
        self.assertAlmostEqual(line.quote_price_pp, 22.0)

    def test_price_with_vat_is_kept(self):
        line = self._requested_line()
        self._reply(line, {'precio_persona': 20, 'iva_incluido': True})
        self.assertAlmostEqual(line.quote_price_pp, 20.0)

    def test_menu_prices_without_vat_get_ten_percent_added(self):
        line = self._requested_line()
        self._reply(line, {'iva_incluido': False, 'menus': [
            {'nombre': 'Menú A 2027', 'precio_persona': 30, 'platos': []},
            {'nombre': 'Menú B 2027', 'precio_persona': 40, 'platos': []}]})
        prices = sorted(self.env['restagrup.restaurant.menu'].search(
            [('partner_id', '=', self.restaurant.id)]).mapped('cost_price'))
        self.assertEqual(prices, [33.0, 44.0])

    def test_reply_without_single_price_is_marked_as_replied(self):
        line = self._requested_line()
        self.assertFalse(line.quote_reply_date)
        self._reply(line, {'menus': []})
        self.assertTrue(line.quote_reply_date)
        self.assertEqual(line.etiqueta, 'solicitado')
