# -*- coding: utf-8 -*-
import itertools
import json
from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
RAW_EMAIL = """Return-Path: <{sender}>
To: peticiones@restagrup.example.com
From: {sender}
Subject: {subject}
Message-Id: <m-{uid}@agencia.example.com>
Content-Type: text/plain; charset=utf-8

{body}
"""
_uid = itertools.count(1)
SENDER = 'ana@agencia.example.com'


@tagged('post_install', '-at_install')
class TestIncomingMatching(TransactionCase):
    """A5+: un cambio de un cliente con varios grupos abiertos se enlaza solo al grupo correcto -- primero por
    ciudad y fecha, y si sigue habiendo empate, la IA elige entre los candidatos. Solo va a revisión si no sabe."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['restagrup.ai.log']
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.classify_incoming')]).unlink()
        cls.partner = cls.env['res.partner'].create({'name': 'Ana A5m', 'email': SENDER})

    def _lead(self, name, events):
        lead = self.env['crm.lead'].create({'name': name, 'partner_id': self.partner.id, 'email_from': SENDER})
        for city, day, pax in events:
            self.env['restagrup.lead.event'].create({
                'lead_id': lead.id, 'city': city, 'event_date': day, 'pax': pax})
        return lead

    def _receive(self, hints=None, pick='none', subject='Cambio en el grupo', body='Seremos 42.', category='group_change'):
        """`hints`: lo que la clasificación extrae del correo; `pick`: lo que contesta la IA al desempatar
        ('none' = no sabe, o un id de lead)."""
        calls = {'match': 0}

        def fake(system_prompt, user_content):
            lowered = system_prompt.lower()
            if 'clasific' in lowered:
                return dict({'categoria': category, 'resumen': 'resumen'}, **(hints or {})), 'groq'
            if 'candidatos' in lowered:
                calls['match'] += 1
                if pick == 'fail':
                    return None, None
                return {'lead_id': None if pick == 'none' else pick}, 'groq'
            return {'eventos': []}, 'groq'
        raw = RAW_EMAIL.format(sender=SENDER, subject=subject, body=body, uid=next(_uid))
        leads = self.env['crm.lead'].search([])
        inbox = self.env['restagrup.inbox.mail'].search([])
        with patch(LLM_PATH, side_effect=fake):
            self.env['mail.thread'].message_process('crm.lead', raw)
        return (self.env['crm.lead'].search([]) - leads, self.env['restagrup.inbox.mail'].search([]) - inbox, calls)

    def _posted(self, lead, text='Seremos 42'):
        return text in ' '.join(lead.message_ids.mapped('body'))

    # --- desempate por ciudad y fecha ---

    def test_city_and_date_pick_the_right_lead(self):
        madrid = self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Costa del Sol', [('Málaga', date(2026, 11, 13), 32), ('Marbella', date(2026, 11, 14), 32)])
        leads, inbox, calls = self._receive({'ciudad': 'Madrid', 'fecha': '2026-11-20'})
        self.assertFalse(leads)
        self.assertFalse(inbox)
        self.assertTrue(self._posted(madrid))
        self.assertEqual(calls['match'], 0)  # no hizo falta preguntar a la IA

    def test_city_alone_is_enough_when_only_one_lead_has_it(self):
        madrid = self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Costa del Sol', [('Málaga', date(2026, 11, 13), 32)])
        _leads, inbox, _calls = self._receive({'ciudad': 'Madrid'})
        self.assertFalse(inbox)
        self.assertTrue(self._posted(madrid))

    def test_city_matching_ignores_case_and_accents(self):
        malaga = self._lead('Costa del Sol', [('Málaga', date(2026, 11, 13), 32)])
        self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        _leads, inbox, _calls = self._receive({'ciudad': 'MALAGA'})
        self.assertFalse(inbox)
        self.assertTrue(self._posted(malaga))

    def test_date_alone_picks_when_only_one_lead_has_it(self):
        target = self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Comida Sevilla', [('Sevilla', date(2026, 12, 5), 20)])
        _leads, inbox, _calls = self._receive({'fecha': '2026-11-20'})
        self.assertFalse(inbox)
        self.assertTrue(self._posted(target))

    def test_a_lead_with_both_city_and_date_beats_one_with_only_the_city(self):
        target = self._lead('Cena Madrid 20', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Cena Madrid 27', [('Madrid', date(2026, 11, 27), 50)])
        _leads, inbox, calls = self._receive({'ciudad': 'Madrid', 'fecha': '2026-11-20'})
        self.assertFalse(inbox)
        self.assertTrue(self._posted(target))
        self.assertEqual(calls['match'], 0)

    # --- si sigue habiendo empate, elige la IA ---

    def test_a_tie_is_settled_by_the_ai_choosing_among_the_candidates(self):
        first = self._lead('Cena Madrid A', [('Madrid', date(2026, 11, 20), 35)])
        second = self._lead('Cena Madrid B', [('Madrid', date(2026, 11, 20), 50)])
        _leads, inbox, calls = self._receive({'ciudad': 'Madrid', 'fecha': '2026-11-20'}, pick=second.id)
        self.assertEqual(calls['match'], 1)
        self.assertFalse(inbox)
        self.assertTrue(self._posted(second))
        self.assertFalse(self._posted(first))
        log = self.Log.search([('kind', '=', 'lead_matching')])
        self.assertEqual(log.state, 'auto')

    def test_no_hints_at_all_also_goes_to_the_ai(self):
        a = self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Comida Sevilla', [('Sevilla', date(2026, 12, 5), 20)])
        _leads, inbox, calls = self._receive(None, pick=a.id)
        self.assertEqual(calls['match'], 1)
        self.assertFalse(inbox)
        self.assertTrue(self._posted(a))

    def test_ai_saying_it_does_not_know_goes_to_review(self):
        self._lead('Cena Madrid A', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Cena Madrid B', [('Madrid', date(2026, 11, 20), 50)])
        _leads, inbox, _calls = self._receive({'ciudad': 'Madrid'}, pick='none')
        self.assertEqual(inbox.category, 'group_change')

    def test_ai_choosing_a_lead_that_is_not_a_candidate_is_ignored(self):
        self._lead('Cena Madrid A', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Cena Madrid B', [('Madrid', date(2026, 11, 20), 50)])
        stranger = self.env['crm.lead'].create({'name': 'De otro cliente', 'email_from': 'otro@otra.example.com'})
        _leads, inbox, _calls = self._receive({'ciudad': 'Madrid'}, pick=stranger.id)
        self.assertTrue(inbox)
        self.assertFalse(self._posted(stranger))

    def test_ai_failure_while_settling_a_tie_goes_to_review(self):
        self._lead('Cena Madrid A', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Cena Madrid B', [('Madrid', date(2026, 11, 20), 50)])
        _leads, inbox, _calls = self._receive({'ciudad': 'Madrid'}, pick='fail')
        self.assertTrue(inbox)

    def test_the_ai_only_sees_the_senders_open_leads(self):
        self._lead('Cena Madrid A', [('Madrid', date(2026, 11, 20), 35)])
        self._lead('Cena Madrid B', [('Madrid', date(2026, 11, 20), 50)])
        seen = {}

        def fake(system_prompt, user_content):
            if 'clasific' in system_prompt.lower():
                return {'categoria': 'group_change', 'resumen': 'r'}, 'groq'
            if 'candidatos' in system_prompt.lower():
                seen['content'] = user_content
                return {'lead_id': None}, 'groq'
            return {'eventos': []}, 'groq'
        self.env['crm.lead'].create({'name': 'Secreto de otro cliente', 'email_from': 'otro@otra.example.com'})
        raw = RAW_EMAIL.format(sender=SENDER, subject='Cambio', body='Seremos 42.', uid=next(_uid))
        with patch(LLM_PATH, side_effect=fake):
            self.env['mail.thread'].message_process('crm.lead', raw)
        self.assertIn('Cena Madrid A', seen['content'])
        self.assertNotIn('Secreto de otro cliente', seen['content'])

    # --- lo que ya funcionaba sigue igual ---

    def test_a_single_open_lead_is_still_linked_without_any_ai_call(self):
        only = self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        _leads, inbox, calls = self._receive({'ciudad': 'Sevilla'})
        self.assertFalse(inbox)
        self.assertTrue(self._posted(only))
        self.assertEqual(calls['match'], 0)

    def test_hints_are_stored_in_the_classification_log(self):
        self._lead('Cena Madrid', [('Madrid', date(2026, 11, 20), 35)])
        self._receive({'ciudad': 'Madrid', 'fecha': '2026-11-20'})
        log = self.Log.search([('kind', '=', 'mail_classification')])
        self.assertEqual(json.loads(log.output)['ciudad'], 'Madrid')
