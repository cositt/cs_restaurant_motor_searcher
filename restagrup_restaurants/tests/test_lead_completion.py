# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestLeadCompletion(TransactionCase):
    """Una petición clara no pasa por nadie; si faltan datos, la IA pide a la agencia solo lo que falta y rellena
    el lead con la respuesta. Solo si tras dos peticiones sigue incompleta, la mira una persona."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Pending = cls.env['restagrup.pending.mail']
        cls.Log = cls.env['restagrup.ai.log']
        cls.owner = cls.env['res.users'].create({'name': 'Comercial A5c', 'login': 'com_a5c', 'email': 'c5c@example.test'})
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')

    # --- helpers ---

    def _extract(self, events, lead=None, email_from='"Ana" <ana@agencia.example.com>'):
        """Pasa un correo de petición por la extracción de la IA con estos eventos."""
        lead = lead or self.env['crm.lead'].create({
            'name': 'Petición A5c', 'email_from': email_from, 'user_id': self.owner.id})
        data = {'eventos': events, 'ciudad': events[0].get('ciudad') if events else None}
        with patch(LLM_PATH, return_value=(data, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>texto del correo</p>'})
        return lead

    def _event(self, city='Madrid', day='2026-11-20', kind='cena', pax=30):
        return {'ciudad': city, 'fecha': day, 'tipo': kind, 'pax': pax, 'notas': None}

    def _requests(self, lead):
        return self.Pending.search([('request_lead_id', '=', lead.id), ('kind', '=', 'lead_data_request')])

    def _emails(self, lead):
        return lead.message_ids.filtered(lambda m: m.message_type == 'email' and m.author_id != lead.partner_id
                                         and m.subject and 'Datos' in m.subject)

    def _reply(self, lead, answer, body='<p>Respuesta de la agencia</p>'):
        with patch(LLM_PATH, return_value=(answer, 'groq')):
            lead.message_update({'body': body})

    def _toasts(self, sendone):
        return [call.args[2] for call in sendone.call_args_list if call.args[1] == 'simple_notification']

    # --- petición completa: nadie interviene ---

    def test_complete_request_needs_no_review_and_no_request(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            lead = self._extract([self._event()])
        log = self.Log.search([('kind', '=', 'lead_extraction'), ('source_res_id', '=', lead.id)])
        self.assertEqual(log.state, 'auto')
        self.assertFalse(log.activity_ids)
        self.assertFalse(self._requests(lead))
        toasts = self._toasts(sendone)
        self.assertEqual(len(toasts), 1)
        self.assertFalse(toasts[0]['sticky'])

    # --- petición incompleta: la IA pide lo que falta ---

    def test_missing_items_are_listed_precisely(self):
        lead = self._extract([self._event(city='Sevilla', day=None, pax=0)])
        text = lead._restagrup_missing_request_data()
        self.assertEqual(len(text), 2)
        self.assertTrue(any('Fecha' in item and 'Sevilla' in item for item in text))
        self.assertTrue(any('comensales' in item.lower() for item in text))

    def test_incomplete_request_queues_an_email_to_the_sender_asking_only_for_what_is_missing(self):
        lead = self._extract([self._event(city='Sevilla', day=None)])
        request = self._requests(lead)
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, 'pending')
        self.assertEqual(request.recipient_email, 'ana@agencia.example.com')
        self.assertIn('Fecha', request.body)
        self.assertNotIn('comensales', request.body.lower())
        self.assertFalse(self._emails(lead))
        self.assertEqual(lead.restagrup_data_request_count, 0)

    def test_incomplete_request_does_not_ask_a_person_to_review(self):
        lead = self._extract([self._event(day=None)])
        log = self.Log.search([('kind', '=', 'lead_extraction'), ('source_res_id', '=', lead.id)])
        self.assertEqual(log.state, 'auto')
        self.assertFalse(log.activity_ids)

    def test_automatic_mode_sends_the_request_straight_away(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        lead = self._extract([self._event(day=None)])
        self.assertFalse(self._requests(lead))
        self.assertEqual(len(self._emails(lead)), 1)
        self.assertEqual(lead.restagrup_data_request_count, 1)

    def test_approving_the_queued_request_sends_it_and_counts_it(self):
        lead = self._extract([self._event(day=None)])
        request = self._requests(lead)
        request.action_approve()
        self.assertEqual(request.state, 'sent')
        self.assertEqual(len(self._emails(lead)), 1)
        self.assertEqual(lead.restagrup_data_request_count, 1)

    def test_a_queued_request_is_discarded_if_the_lead_got_complete_meanwhile(self):
        lead = self._extract([self._event(day=None)])
        request = self._requests(lead)
        lead.restagrup_event_ids.event_date = date(2026, 11, 20)
        request.action_approve()
        self.assertEqual(request.state, 'discarded')
        self.assertFalse(self._emails(lead))

    def test_no_duplicate_request_while_one_is_waiting(self):
        lead = self._extract([self._event(day=None)])
        lead._restagrup_ask_for_missing_data()
        self.assertEqual(len(self._requests(lead)), 1)

    def test_without_a_sender_email_a_person_is_asked_straight_away(self):
        lead = self.env['crm.lead'].create({'name': 'Sin email A5c', 'user_id': self.owner.id})
        self._extract([self._event(day=None)], lead=lead)
        self.assertFalse(self._requests(lead))
        self.assertEqual(lead.activity_ids.user_id, self.owner)

    # --- la respuesta de la agencia rellena el lead ---

    def _asked(self, events=None):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        lead = self._extract(events or [self._event(city='Sevilla', day=None, pax=0)])
        return lead, lead.restagrup_event_ids

    def test_the_reply_fills_the_blanks_and_completes_the_request(self):
        lead, event = self._asked()
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            self._reply(lead, {'eventos': [{'id': event.id, 'fecha': '2026-12-12', 'pax': 25}]})
        self.assertEqual(event.event_date, date(2026, 12, 12))
        self.assertEqual(event.pax, 25)
        self.assertFalse(lead._restagrup_missing_request_data())
        self.assertFalse(self._requests(lead))
        self.assertEqual(lead.restagrup_data_request_count, 1)  # no hizo falta preguntar otra vez
        self.assertFalse(lead.activity_ids)
        self.assertTrue(self.Log.search([('kind', '=', 'lead_completion'), ('source_res_id', '=', lead.id)]))
        self.assertTrue(self._toasts(sendone))

    def test_the_reply_never_overwrites_what_the_lead_already_has(self):
        lead, event = self._asked([self._event(city='Sevilla', day=None, pax=40)])
        self._reply(lead, {'eventos': [{'id': event.id, 'fecha': '2026-12-12', 'pax': 99}]})
        self.assertEqual(event.pax, 40)
        self.assertEqual(event.event_date, date(2026, 12, 12))

    def test_ids_that_are_not_events_of_this_lead_are_ignored(self):
        lead, event = self._asked()
        other = self.env['restagrup.lead.event'].create({
            'lead_id': self.env['crm.lead'].create({'name': 'Otro A5c'}).id, 'city': 'Bilbao'})
        self._reply(lead, {'eventos': [{'id': other.id, 'fecha': '2026-12-12', 'pax': 25}]})
        self.assertFalse(other.event_date)
        self.assertFalse(event.event_date)

    def test_a_reply_that_leaves_gaps_asks_once_more(self):
        lead, event = self._asked()
        self._reply(lead, {'eventos': [{'id': event.id, 'fecha': '2026-12-12'}]})  # sigue sin comensales
        self.assertEqual(lead.restagrup_data_request_count, 2)
        self.assertEqual(len(self._emails(lead)), 2)
        self.assertIn('comensales', self._emails(lead)[0].body.lower())

    def test_after_two_requests_a_person_takes_over_and_nothing_more_is_sent(self):
        lead, event = self._asked()
        self._reply(lead, {'eventos': [{'id': event.id, 'fecha': '2026-12-12'}]})
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            self._reply(lead, {'eventos': []})  # la agencia no aclara nada más
        self.assertEqual(lead.restagrup_data_request_count, 2)
        self.assertEqual(len(self._emails(lead)), 2)
        self.assertEqual(lead.activity_ids.user_id, self.owner)
        self.assertIn('Faltan datos', lead.activity_ids.summary)
        self.assertTrue(any(t['sticky'] for t in self._toasts(sendone)))

    def test_an_ai_failure_reading_the_reply_hands_over_to_a_person_without_asking_again(self):
        lead, _event = self._asked()
        self._reply(lead, None)
        self.assertEqual(lead.restagrup_data_request_count, 1)
        self.assertTrue(lead.activity_ids.filtered(lambda a: 'Faltan datos' in a.summary))

    def test_a_message_on_a_lead_that_was_never_asked_is_not_processed(self):
        lead = self._extract([self._event()])
        with patch(LLM_PATH, side_effect=AssertionError('no debe llamar a la IA')):
            lead.message_update({'body': '<p>Hola de nuevo</p>'})
        self.assertFalse(self.Log.search([('kind', '=', 'lead_completion')]))

    def test_a_complete_lead_ignores_later_messages(self):
        lead, event = self._asked()
        self._reply(lead, {'eventos': [{'id': event.id, 'fecha': '2026-12-12', 'pax': 25}]})
        with patch(LLM_PATH, side_effect=AssertionError('no debe llamar a la IA')):
            lead.message_update({'body': '<p>Gracias</p>'})

    # --- sin implicar al resto ---

    def test_lead_level_data_counts_when_the_ai_found_no_events(self):
        lead = self.env['crm.lead'].create({
            'name': 'Sin eventos A5c', 'email_from': 'x@agencia.example.com',
            'restagrup_city': 'Madrid', 'restagrup_pax': 30, 'restagrup_service_date': date(2026, 11, 20)})
        self.assertFalse(lead._restagrup_missing_request_data())

    def test_nothing_at_all_asks_for_the_three_basics(self):
        lead = self.env['crm.lead'].create({'name': 'Vacío A5c', 'email_from': 'x@agencia.example.com'})
        self.assertEqual(len(lead._restagrup_missing_request_data()), 3)
