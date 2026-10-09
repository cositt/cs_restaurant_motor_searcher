# -*- coding: utf-8 -*-
import itertools
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
RAW_EMAIL = """Return-Path: <{sender}>
To: peticiones@restagrup.example.com
From: {sender}
Subject: {subject}
Message-Id: <a4-{uid}@agencia.example.com>
Content-Type: text/plain; charset=utf-8

{body}
"""
_uid = itertools.count(1)


@tagged('post_install', '-at_install')
class TestAiActivityEmail(TransactionCase):
    """A4: lo que la IA hace con los correos entrantes queda registrado, se cierra con la revisión humana y
    avisa si falla o si detecta una incidencia."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['restagrup.ai.log']
        cls.alert_user = cls.env['res.users'].create({'name': 'Alertas A4e', 'login': 'alert_a4e', 'email': 'a4e@example.test'})
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.alert_user_id', str(cls.alert_user.id))
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.classify_incoming')]).unlink()

    def _fake(self, category='new_request', extraction='ok'):
        def fake(system_prompt, user_content):
            if 'clasific' in system_prompt.lower():
                if category is None:
                    return None, None
                return {'categoria': category, 'resumen': 'resumen'}, 'groq'
            if extraction is None:
                return None, None
            return {'eventos': [{'ciudad': 'Madrid', 'pax': 30, 'fecha': '2026-11-20'}],
                    'ciudad': 'Madrid', 'num_pax': 30}, 'groq'
        return fake

    def _receive(self, category='new_request', extraction='ok', subject='Petición A4', sender='ana@agencia.example.com',
                 body='Hola, somos 30.'):
        raw = RAW_EMAIL.format(sender=sender, subject=subject, body=body, uid=next(_uid))
        before = self.Log.search([])
        with patch(LLM_PATH, side_effect=self._fake(category, extraction)):
            self.env['mail.thread'].message_process('crm.lead', raw)
        return self.Log.search([]) - before

    # --- extracción del lead ---

    def test_complete_lead_extraction_is_logged_as_automatic_with_the_lead_as_source(self):
        logs = self._receive('new_request')
        extraction = logs.filtered(lambda l: l.kind == 'lead_extraction')
        self.assertEqual(len(extraction), 1)
        self.assertEqual(extraction.state, 'auto')  # petición completa: no la revisa nadie
        self.assertEqual(extraction.source_model, 'crm.lead')
        lead = self.env['crm.lead'].browse(extraction.source_res_id)
        self.assertEqual(lead.restagrup_city, 'Madrid')

    def test_failed_lead_extraction_logs_error_and_alerts(self):
        logs = self._receive('new_request', extraction=None)
        extraction = logs.filtered(lambda l: l.kind == 'lead_extraction')
        self.assertEqual(extraction.state, 'error')
        self.assertEqual(extraction.activity_ids.user_id, self.alert_user)

    # --- clasificación de correos ---

    def test_new_request_classification_is_automatic(self):
        logs = self._receive('new_request')
        classification = logs.filtered(lambda l: l.kind == 'mail_classification')
        self.assertEqual(classification.state, 'auto')
        self.assertIn('Petición A4', classification.source_label)
        self.assertIn('ana@agencia.example.com', classification.source_label)

    def test_classification_failure_is_logged_as_error_and_lead_is_still_created(self):
        leads_before = self.env['crm.lead'].search_count([])
        logs = self._receive(None)
        classification = logs.filtered(lambda l: l.kind == 'mail_classification')
        self.assertEqual(classification.state, 'error')
        self.assertEqual(self.env['crm.lead'].search_count([]), leads_before + 1)

    def test_mail_sent_to_review_is_pending_and_linked_to_the_inbox_item(self):
        logs = self._receive('invoice', subject='Factura A4')
        classification = logs.filtered(lambda l: l.kind == 'mail_classification')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Factura A4')])
        self.assertEqual(classification.state, 'pending')
        self.assertEqual(inbox.ai_log_id, classification)

    def test_marking_the_inbox_item_done_confirms_the_classification(self):
        self._receive('invoice', subject='Factura A4b')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Factura A4b')])
        inbox.action_mark_done()
        self.assertEqual(inbox.ai_log_id.state, 'confirmed')
        self.assertEqual(inbox.ai_log_id.reviewed_by, self.env.user)

    def test_creating_a_lead_from_the_inbox_marks_the_classification_as_corrected(self):
        self._receive('other', subject='Era petición A4')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Era petición A4')])
        with patch(LLM_PATH, side_effect=self._fake()):
            inbox.action_create_lead()
        self.assertEqual(inbox.ai_log_id.state, 'corrected')

    # --- incidencias ---

    def test_incident_creates_an_urgent_activity_on_the_inbox_item_and_nothing_else(self):
        leads_before = self.env['crm.lead'].search_count([])
        self._receive('incident', subject='Restaurante sin reserva A4')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Restaurante sin reserva A4')])
        self.assertEqual(self.env['crm.lead'].search_count([]), leads_before)
        self.assertEqual(inbox.activity_ids.user_id, self.alert_user)
        self.assertIn('URGENTE', inbox.activity_ids.summary)

    def test_incident_goes_to_the_owner_of_the_sender_lead_when_known(self):
        owner = self.env['res.users'].create({'name': 'Comercial A4e', 'login': 'com_a4e', 'email': 'c4e@example.test'})
        partner = self.env['res.partner'].create({'name': 'Agente A4', 'email': 'ana@agencia.example.com'})
        self.env['crm.lead'].create({'name': 'Grupo A4', 'partner_id': partner.id,
                                     'email_from': 'ana@agencia.example.com', 'user_id': owner.id})
        self._receive('incident', subject='Incidencia con grupo')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Incidencia con grupo')])
        self.assertEqual(inbox.activity_ids.user_id, owner)

    def test_non_incident_creates_no_activity(self):
        self._receive('invoice', subject='Otra factura A4')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Otra factura A4')])
        self.assertFalse(inbox.activity_ids)

    # --- avisos en la UI (contador del reloj + aviso emergente) ---

    def test_complete_lead_extraction_asks_nobody_to_review_it(self):
        logs = self._receive('new_request', subject='Petición con aviso')
        extraction = logs.filtered(lambda l: l.kind == 'lead_extraction')
        self.assertFalse(extraction.activity_ids)

    def test_mail_sent_to_review_has_an_activity_that_goes_away_when_reviewed(self):
        self._receive('invoice', subject='Factura con aviso')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Factura con aviso')])
        self.assertEqual(inbox.ai_log_id.activity_ids.user_id, self.alert_user)
        inbox.action_mark_done()
        self.assertFalse(inbox.ai_log_id.activity_ids)

    def test_incident_has_its_urgent_activity_and_no_extra_review_activity(self):
        self._receive('incident', subject='Incidencia con aviso')
        inbox = self.env['restagrup.inbox.mail'].search([('name', '=', 'Incidencia con aviso')])
        self.assertIn('URGENTE', inbox.activity_ids.summary)
        self.assertFalse(inbox.ai_log_id.activity_ids)

    def test_automatic_classification_of_a_new_request_makes_no_noise(self):
        logs = self._receive('new_request', subject='Sin ruido')
        classification = logs.filtered(lambda l: l.kind == 'mail_classification')
        self.assertFalse(classification.activity_ids)
