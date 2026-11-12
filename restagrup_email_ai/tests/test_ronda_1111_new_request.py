# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11: Conchita (Sol y Nubes) pidió «grupo adulto de médicos, comida 9 de diciembre, Sevilla,
48 personas». Se metió en el expediente «Grupo adulto» (Sevilla, 18/11) en vez de crear una petición nueva: el nombre
aparecía en el texto y la ciudad coincidía. Otra fecha es otro servicio.

- Si el correo trae una fecha y ninguno de los grupos abiertos del remitente la tiene, no se enlaza a ninguno.
- Una respuesta (agency_reply) con esa fecha que no es de ningún grupo es una petición nueva: se crea.
- Un cambio (group_change) puede ser un cambio de fecha: va a revisión, no se enlaza a ciegas.
- La clasificación sabe que pedir disponibilidad para otro grupo u otra fecha es una petición nueva aunque sea un «Re:».
"""
import itertools
from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.restagrup_email_ai.models.mail_thread import CLASSIFY_SYSTEM_PROMPT

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
RAW_EMAIL = """Return-Path: <{sender}>
To: peticiones@restagrup.example.com
From: {sender}
Subject: Re: presupuesto grupo malaga
Message-Id: <r1111-{uid}@agencia.example.com>
Content-Type: text/plain; charset=utf-8

desde la agencia sol y nubes le solicitamos disponibilidad para grupo adulto de medicos para este servicio:
comida 9 de diciembre, Sevilla centro, 48 personas + chofer y guia, menu de paso
"""
_uid = itertools.count(1)
SENDER = 'conchita@solynubes.example.com'


@tagged('post_install', '-at_install')
class TestRonda1111NewRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.classify_incoming')]).unlink()
        cls.partner = cls.env['res.partner'].create({'name': 'Conchita 1111', 'email': SENDER})
        cls.group = cls.env['crm.lead'].create({
            'name': 'Grupo adulto', 'partner_id': cls.partner.id, 'email_from': SENDER})
        cls.env['restagrup.lead.event'].create({
            'lead_id': cls.group.id, 'city': 'Sevilla', 'event_date': date(2026, 11, 18), 'pax': 50})

    def _receive(self, category, day='2026-12-09'):
        def fake(system_prompt, _user_content):
            lowered = system_prompt.lower()
            if 'clasific' in lowered:
                return {'categoria': category, 'resumen': 'grupo de médicos', 'ciudad': 'Sevilla',
                        'fecha': day, 'num_pax': 48}, 'groq'
            if 'candidatos' in lowered:
                return {'lead_id': self.group.id}, 'groq'
            return {'eventos': []}, 'groq'
        before_leads = self.env['crm.lead'].search([])
        before_inbox = self.env['restagrup.inbox.mail'].search([])
        raw = RAW_EMAIL.format(sender=SENDER, uid=next(_uid))
        with patch(LLM_PATH, side_effect=fake):
            self.env['mail.thread'].message_process('crm.lead', raw)
        return (self.env['crm.lead'].search([]) - before_leads,
                self.env['restagrup.inbox.mail'].search([]) - before_inbox)

    def _in_group(self):
        return 'medicos' in ' '.join(self.group.message_ids.mapped('body'))

    def test_reply_with_another_date_creates_a_new_request(self):
        leads, inbox = self._receive('agency_reply')
        self.assertEqual(len(leads), 1)
        self.assertFalse(inbox)
        self.assertFalse(self._in_group())

    def test_change_with_another_date_goes_to_review(self):
        leads, inbox = self._receive('group_change')
        self.assertFalse(leads)
        self.assertEqual(len(inbox), 1)
        self.assertFalse(self._in_group())

    def test_same_date_still_links_to_the_group(self):
        leads, inbox = self._receive('agency_reply', day='2026-11-18')
        self.assertFalse(leads)
        self.assertFalse(inbox)
        self.assertTrue(self._in_group())

    def test_classification_prompt_explains_other_date_is_a_new_request(self):
        prompt = CLASSIFY_SYSTEM_PROMPT.lower()
        self.assertIn('otra fecha', prompt)
        self.assertIn('re:', prompt)
