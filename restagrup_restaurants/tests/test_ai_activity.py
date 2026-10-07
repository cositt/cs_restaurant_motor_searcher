# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestAiActivityRestaurants(TransactionCase):
    """A4: importes, datos de ficha y extracción del lead: se registran, se cierran con la revisión humana
    (confirmado / corregido / descartado) y avisan si fallan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['restagrup.ai.log']
        cls.owner = cls.env['res.users'].create({'name': 'Comercial A4r', 'login': 'com_a4r', 'email': 'c4r@example.test'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo A4r', 'user_id': cls.owner.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 20, 'user_id': cls.owner.id})
        cls.partner = cls.env['res.partner'].create({
            'name': 'Casa A4r', 'is_restaurant': True, 'email': 'casa-a4r@example.com',
            'restaurant_capacity': 50, 'restaurant_language': 'es'})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': 'Casa A4r', 'partner_id': cls.partner.id,
            'email': 'casa-a4r@example.com', 'etiqueta': 'solicitado'})

    def _reply(self, line, data, body='<p>Son 1.200 € en total.</p>'):
        with patch(LLM_PATH, return_value=(data, 'groq')):
            line.message_update({'body': body})

    def _logs(self, kind, source):
        return self.Log.search([('kind', '=', kind), ('source_model', '=', source._name), ('source_res_id', '=', source.id)])

    # --- importe ---

    def test_quote_reply_is_logged_pending(self):
        self._reply(self.line, {'importe': 1200, 'notas': None})
        log = self._logs('quote_extraction', self.line)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.state, 'pending')
        self.assertEqual(json.loads(log.output)['importe'], 1200)

    def test_registering_the_proposed_amount_confirms_the_log(self):
        self._reply(self.line, {'importe': 1200})
        self.line.action_register_quote()
        self.assertEqual(self._logs('quote_extraction', self.line).state, 'confirmed')

    def test_registering_a_different_amount_marks_the_log_as_corrected(self):
        self._reply(self.line, {'importe': 1200})
        self.line.quote_amount = 1100
        self.line.action_register_quote()
        self.assertEqual(self._logs('quote_extraction', self.line).state, 'corrected')

    def test_manual_extraction_from_pasted_text_is_logged_too(self):
        self.line.quote_raw_text = 'Total 900 euros'
        with patch(LLM_PATH, return_value=({'importe': 900}, 'groq')):
            self.line.action_extract_quote_from_text()
        self.assertEqual(self._logs('quote_extraction', self.line).state, 'pending')

    def test_failed_quote_extraction_alerts_the_search_owner(self):
        self._reply(self.line, None)
        log = self._logs('quote_extraction', self.line)
        self.assertEqual(log.state, 'error')
        self.assertEqual(log.activity_ids.user_id, self.owner)

    # --- datos de ficha ---

    def _ask_data(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        self.line.action_request_missing_data()

    def test_data_proposal_is_logged_and_apply_confirms_it(self):
        self._ask_data()
        self._reply(self.line, {'dia_cierre': 'mon', 'responsable': 'Marta'}, body='<p>Cerramos los lunes. Marta.</p>')
        log = self._logs('data_extraction', self.line)
        self.assertEqual(log.state, 'pending')
        self.line.action_apply_data_proposal()
        self.assertEqual(log.state, 'confirmed')

    def test_discarding_the_data_proposal_marks_the_log_discarded(self):
        self._ask_data()
        self._reply(self.line, {'dia_cierre': 'mon'}, body='<p>Lunes.</p>')
        self.line.action_discard_data_proposal()
        self.assertEqual(self._logs('data_extraction', self.line).state, 'discarded')

    def test_data_reply_with_nothing_usable_does_not_wait_for_a_review(self):
        self._ask_data()
        self._reply(self.line, {'dia_cierre': None}, body='<p>Gracias.</p>')
        self.assertEqual(self._logs('data_extraction', self.line).state, 'auto')

    # --- extracción del lead: se confirma al empezar a buscar ---

    def _lead_with_extraction(self, city='Madrid', pax=30):
        lead = self.env['crm.lead'].create({'name': 'Grupo extraído A4r', 'user_id': self.owner.id})
        with patch(LLM_PATH, return_value=({'ciudad': 'Madrid', 'num_pax': 30, 'eventos': []}, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>Cena en Madrid para 30.</p>'})
        lead.write({'restagrup_city': city, 'restagrup_pax': pax})
        return lead

    def test_creating_the_first_search_confirms_an_untouched_extraction(self):
        lead = self._lead_with_extraction()
        self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 30})
        self.assertEqual(self._logs('lead_extraction', lead).state, 'confirmed')

    def test_creating_the_first_search_after_editing_the_data_marks_it_corrected(self):
        lead = self._lead_with_extraction(city='Sevilla', pax=40)
        self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 40})
        self.assertEqual(self._logs('lead_extraction', lead).state, 'corrected')
