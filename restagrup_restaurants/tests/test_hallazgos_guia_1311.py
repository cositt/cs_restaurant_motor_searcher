# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestHallazgosGuia1311(TransactionCase):
    """Hallazgos al capturar la guía en prod (13/11): (1) la nota «Precios dados sin IVA» no va a las notas del
    presupuesto (las ve la agencia), (3) una dirección de Google sin CP también se trocea, (4) la ventana de
    registrar el menú tiene título."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Line = cls.env['restagrup.restaurant.search.line']
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo guía 1311'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'MÁLAGA', 'min_capacity': 40})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Guía', 'is_restaurant': True, 'email': 'guia1311@example.com'})

    def _requested_line(self):
        return self.Line.create({
            'search_id': self.search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'email': self.restaurant.email, 'etiqueta': 'solicitado'})

    # --- (1) ---------------------------------------------------------------------------------------------------
    def test_vat_note_goes_to_the_history_not_to_the_quote_notes(self):
        line = self._requested_line()
        with patch(LLM_PATH, return_value=({'precio_persona': 13, 'iva_incluido': False, 'notas': 'Sin depósito'},
                                           'groq')):
            line.message_update({'body': '<p>13 euros más IVA, sin depósito.</p>'})
        self.assertAlmostEqual(line.quote_price_pp, 14.3)
        self.assertEqual(line.quote_notes, 'Sin depósito')
        self.assertTrue(self.search.message_ids.filtered(lambda m: 'sin IVA' in (m.body or '')))

    def test_vat_note_alone_leaves_quote_notes_empty(self):
        line = self._requested_line()
        line.quote_raw_text = '20 € + IVA'
        with patch(LLM_PATH, return_value=({'precio_persona': 20, 'iva_incluido': False}, 'groq')):
            line.action_extract_quote_from_text()
        self.assertAlmostEqual(line.quote_price_pp, 22.0)
        self.assertFalse(line.quote_notes)
        self.assertTrue(self.search.message_ids.filtered(lambda m: 'sin IVA' in (m.body or '')))

    # --- (3) ---------------------------------------------------------------------------------------------------
    def test_google_address_without_zip_is_split(self):
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Casa Carretería',
            'address': 'Calle Carretería, 92, Málaga, España', 'phone': '952000000'})
        line.action_add_as_partner()
        partner = line.partner_id
        self.assertEqual(partner.street, 'Calle Carretería, 92')
        self.assertEqual(partner.city, 'Málaga')
        self.assertEqual(partner.country_id, self.env.ref('base.es'))
        self.assertEqual(partner.state_id, self.env.ref('base.state_es_ma'))

    def test_google_address_without_zip_nor_country_is_split(self):
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Casa Carretería 2',
            'address': 'Calle Carretería, 92, Málaga', 'phone': '952000001'})
        line.action_add_as_partner()
        self.assertEqual(line.partner_id.street, 'Calle Carretería, 92')
        self.assertEqual(line.partner_id.city, 'Málaga')
        self.assertEqual(line.partner_id.country_id, self.env.ref('base.es'))

    def test_address_not_ending_in_the_city_keeps_the_street(self):
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Casa Barrio',
            'address': 'Calle Larios, 5, Centro', 'phone': '952000002'})
        line.action_add_as_partner()
        self.assertEqual(line.partner_id.street, 'Calle Larios, 5, Centro')
        self.assertEqual(line.partner_id.city, 'MÁLAGA')

    # --- (4) ---------------------------------------------------------------------------------------------------
    def test_quote_form_window_has_a_title(self):
        action = self._requested_line().action_open_quote_form()
        self.assertEqual(action.get('name'), 'Registrar menú de Casa Guía')

    def test_extract_from_text_window_has_a_title(self):
        line = self._requested_line()
        line.quote_raw_text = '20 € IVA incluido'
        with patch(LLM_PATH, return_value=({'precio_persona': 20, 'iva_incluido': True}, 'groq')):
            action = line.action_extract_quote_from_text()
        self.assertEqual(action.get('name'), 'Registrar menú de Casa Guía')
