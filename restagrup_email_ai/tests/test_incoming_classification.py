# -*- coding: utf-8 -*-
import itertools
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
RAW_EMAIL = """Return-Path: <{sender}>
To: peticiones@restagrup.example.com
From: {sender}
Subject: {subject}
Message-Id: <a5-{uid}@agencia.example.com>
Content-Type: text/plain; charset=utf-8

{body}
"""
_uid = itertools.count(1)


@tagged('post_install', '-at_install')
class TestIncomingClassification(TransactionCase):
    """A5: antes de crear un lead, la IA clasifica el correo. Solo «petición nueva» crea lead; cambios y
    respuestas se enlazan al lead que se reconozca; el resto va a «Correos por revisar» sin crear nada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env['crm.lead']
        cls.Inbox = cls.env['restagrup.inbox.mail']
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.classify_incoming')]).unlink()

    def _fake_llm(self, category, summary='resumen de prueba'):
        calls = {'classify': 0, 'extract': 0}

        def fake(system_prompt, user_content):
            if 'clasific' in system_prompt.lower():
                calls['classify'] += 1
                if category is None:
                    return None, None
                return {'categoria': category, 'resumen': summary}, 'groq'
            calls['extract'] += 1
            return {'eventos': [{'ciudad': 'Madrid', 'pax': 30}], 'ciudad': 'Madrid', 'num_pax': 30}, 'groq'
        return fake, calls

    def _receive(self, category, subject='Petición de grupo', body='Hola, somos 30 personas.',
                 sender='ana@agencia.example.com'):
        fake, calls = self._fake_llm(category)
        leads_before = self.Lead.search([])
        inbox_before = self.Inbox.search([])
        raw = RAW_EMAIL.format(sender=sender, subject=subject, body=body, uid=next(_uid))
        with patch(LLM_PATH, side_effect=fake):
            self.env['mail.thread'].message_process('crm.lead', raw)
        return self.Lead.search([]) - leads_before, self.Inbox.search([]) - inbox_before, calls

    # --- qué crea cada categoría ---

    def test_new_request_creates_lead_and_extracts(self):
        leads, inbox, calls = self._receive('new_request')
        self.assertEqual(len(leads), 1)
        self.assertFalse(inbox)
        self.assertEqual(calls['extract'], 1)
        self.assertEqual(leads.restagrup_city, 'Madrid')

    def test_invoice_incident_and_other_go_to_review_without_creating_a_lead(self):
        for category in ('invoice', 'incident', 'other'):
            leads, inbox, calls = self._receive(category, subject='Asunto %s' % category)
            self.assertFalse(leads, category)
            self.assertEqual(len(inbox), 1, category)
            self.assertEqual(inbox.category, category)
            self.assertEqual(inbox.state, 'to_review')
            self.assertEqual(inbox.name, 'Asunto %s' % category)
            self.assertEqual(inbox.summary, 'resumen de prueba')
            self.assertIn('agencia.example.com', inbox.email_from)
            self.assertEqual(calls['extract'], 0)

    def test_review_item_keeps_the_original_text(self):
        _leads, inbox, _calls = self._receive('invoice', body='Adjunto la factura 123.')
        self.assertIn('factura 123', ' '.join(inbox.message_ids.mapped('body')))

    # --- seguridad: ante la duda se crea el lead ---

    def test_llm_failure_still_creates_the_lead(self):
        leads, inbox, _calls = self._receive(None)
        self.assertEqual(len(leads), 1)
        self.assertFalse(inbox)

    def test_unknown_category_still_creates_the_lead(self):
        leads, inbox, _calls = self._receive('banana')
        self.assertEqual(len(leads), 1)
        self.assertFalse(inbox)

    def test_classification_can_be_switched_off(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.classify_incoming', 'disabled')
        leads, inbox, calls = self._receive('invoice')
        self.assertEqual(len(leads), 1)
        self.assertFalse(inbox)
        self.assertEqual(calls['classify'], 0)

    # --- cambios de un grupo existente ---

    def _lead_for(self, sender, name='Grupo existente'):
        partner = self.env['res.partner'].create({'name': 'Agente', 'email': sender})
        return self.Lead.create({'name': name, 'partner_id': partner.id, 'email_from': sender})

    def test_change_from_sender_with_one_open_lead_is_linked_to_it(self):
        lead = self._lead_for('ana@agencia.example.com')
        leads, inbox, _calls = self._receive('group_change', body='Pasamos de 30 a 35.')
        self.assertFalse(leads)
        self.assertFalse(inbox)
        self.assertIn('de 30 a 35', ' '.join(lead.message_ids.mapped('body')))

    def test_change_with_no_known_lead_goes_to_review(self):
        leads, inbox, _calls = self._receive('group_change', sender='nadie@otra.example.com')
        self.assertFalse(leads)
        self.assertEqual(inbox.category, 'group_change')

    def test_change_with_several_leads_uses_the_one_named_in_the_subject(self):
        self._lead_for('ana@agencia.example.com', name='Cena Sevilla')
        target = self._lead_for('ana@agencia.example.com', name='Comida Valencia')
        leads, inbox, _calls = self._receive('group_change', subject='Cambio en Comida Valencia')
        self.assertFalse(leads)
        self.assertFalse(inbox)
        self.assertIn('Hola, somos 30 personas.', ' '.join(target.message_ids.mapped('body')))

    def test_change_with_several_leads_and_no_reference_goes_to_review(self):
        self._lead_for('ana@agencia.example.com', name='Cena Sevilla')
        self._lead_for('ana@agencia.example.com', name='Comida Valencia')
        leads, inbox, _calls = self._receive('agency_reply', subject='Re: presupuesto')
        self.assertFalse(leads)
        self.assertEqual(inbox.category, 'agency_reply')

    def test_closed_leads_are_not_matched(self):
        lead = self._lead_for('ana@agencia.example.com')
        lead.active = False
        _leads, inbox, _calls = self._receive('group_change')
        self.assertEqual(len(inbox), 1)

    # --- rescate: crear el lead a mano ---

    def test_create_lead_from_review_item(self):
        _leads, inbox, _calls = self._receive('other', subject='Quizá sí era petición', body='Cena para 20 en Bilbao.')
        fake, _calls2 = self._fake_llm('new_request')
        with patch(LLM_PATH, side_effect=fake):
            inbox.action_create_lead()
        self.assertEqual(inbox.state, 'done')
        self.assertTrue(inbox.lead_id)
        self.assertEqual(inbox.lead_id.name, 'Quizá sí era petición')
        self.assertEqual(inbox.lead_id.restagrup_city, 'Madrid')

    def test_mark_done(self):
        _leads, inbox, _calls = self._receive('invoice')
        inbox.action_mark_done()
        self.assertEqual(inbox.state, 'done')

    def test_normal_users_can_work_the_inbox(self):
        _leads, inbox, _calls = self._receive('invoice')
        user = self.env['res.users'].create({
            'name': 'Comercial A5', 'login': 'comercial_a5', 'email': 'a5@example.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        inbox.with_user(user).action_mark_done()
        self.assertEqual(inbox.state, 'done')
