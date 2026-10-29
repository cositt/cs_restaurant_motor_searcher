# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
MENU = {'nombre': 'Menú grupo', 'tipo': 'almuerzo', 'precio_persona': 22.0, 'bebidas': 'Agua y vino',
        'platos': [{'tipo': 'principal', 'nombre': 'Paella'}, {'tipo': 'postre', 'nombre': 'Flan'}]}


@tagged('post_install', '-at_install')
class TestGuiaProdFindings(TransactionCase):
    """Fallos vistos al probar la guía en producción (2026-10-29): avisos de la IA y textos en inglés."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa guía', 'is_restaurant': True, 'email': 'casa-guia@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo IA guía'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Ronda', 'min_capacity': 30})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': 'Casa guía', 'partner_id': cls.restaurant.id,
            'email': 'casa-guia@example.com', 'etiqueta': 'solicitado'})

    def _log(self):
        self.search.invalidate_recordset(['message_ids'])
        return ' '.join(str(body) for body in self.search.message_ids.mapped('body'))

    def _reply(self, importe):
        data = {'importe': importe, 'notas': None, 'menus': [MENU, dict(MENU, nombre='Menú degustación')]}
        with patch(LLM_PATH, return_value=(data, 'groq')):
            self.line.message_update({'body': '<p>Os mandamos dos menús por persona.</p>', 'attachments': []})

    # --- 8: sin importe, el aviso no dice que lo haya ---

    def test_reply_without_amount_does_not_claim_an_amount(self):
        self._reply(None)
        log = self._log()
        self.assertNotIn('importe extraído', log)
        self.assertIn('sin importe', log)

    def test_reply_with_amount_still_says_so(self):
        self._reply(640.0)
        self.assertIn('importe extraído', self._log())

    # --- 13: el aviso de creación del pendiente en español ---

    def test_pending_mail_creation_message_is_in_spanish(self):
        # Los pendientes los crean los crons, que corren sin idioma (inglés).
        mail = self.env['restagrup.pending.mail'].with_context(lang='en_US').create({
            'kind': 'quote_reminder', 'line_id': self.line.id, 'recipient_email': 'casa-guia@example.com',
            'subject': 'Recordatorio', 'body': 'Hola'})
        bodies = ' '.join(str(body) for body in mail.message_ids.mapped('body'))
        self.assertNotIn('created', bodies)

    # --- 11: la cola enseña el restaurante ---

    def test_pending_mail_shows_the_restaurant(self):
        mail = self.env['restagrup.pending.mail'].create({
            'kind': 'quote_reminder', 'line_id': self.line.id, 'recipient_email': 'casa-guia@example.com',
            'subject': 'Recordatorio', 'body': 'Hola'})
        self.assertEqual(mail.restaurant_name, 'Casa guía')
        self.assertEqual(mail.group_id, self.lead)

    # --- 5: la respuesta de un restaurante que no casa con ningún hilo no se pierde ---

    def test_orphan_restaurant_reply_goes_to_review(self):
        raw = """Return-Path: <casa-guia@example.com>
To: restaurantes@restagrup.example.com
From: casa-guia@example.com
Subject: Re: Restagrup Order (Ref P00001)
Message-Id: <orphan-guia-1@example.com>
In-Reply-To: <no-existe-en-odoo@example.com>
Content-Type: text/plain; charset=utf-8

Confirmamos la reserva del grupo.
"""
        inbox = self.env['restagrup.inbox.mail']
        before = inbox.search([])
        self.env['mail.thread'].message_process('restagrup.restaurant.search.line', raw)
        item = inbox.search([]) - before
        self.assertEqual(len(item), 1)
        self.assertEqual(item.name, 'Re: Restagrup Order (Ref P00001)')
        self.assertIn('Confirmamos la reserva', ' '.join(item.message_ids.mapped('body')))
