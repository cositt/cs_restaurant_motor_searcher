# -*- coding: utf-8 -*-
import itertools
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
RAW_EMAIL = """Return-Path: <{sender}>
To: peticiones@restagrup.example.com
From: {sender}
Subject: {subject}
Message-Id: <a5o-{uid}@agencia.example.com>
Content-Type: text/plain; charset=utf-8

{body}
"""
_uid = itertools.count(1)


@tagged('post_install', '-at_install')
class TestIncomingOrdersAndSender(TransactionCase):
    """A5: un cambio o respuesta que cita un presupuesto (S00012) se enlaza a él; y los envíos del sistema
    salen desde la cuenta dedicada si está configurada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().search([('key', 'in', ('restagrup.classify_incoming', 'restagrup.system_sender'))]).unlink()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia A5', 'email': 'agencia-a5@example.com'})
        cls.product = cls.env['product.product'].create({'name': 'Menú A5', 'type': 'service'})

    def _order(self, **vals):
        return self.env['sale.order'].create(dict({
            'partner_id': self.agency.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 5, 'price_unit': 10})],
        }, **vals))

    def _receive(self, category, subject, body='Cambio de comensales.'):
        def fake(system_prompt, user_content):
            return {'categoria': category, 'resumen': 'x'}, 'groq'
        raw = RAW_EMAIL.format(sender='otra@agencia.example.com', subject=subject, body=body, uid=next(_uid))
        leads = self.env['crm.lead'].search([])
        with patch(LLM_PATH, side_effect=fake):
            self.env['mail.thread'].message_process('crm.lead', raw)
        return self.env['crm.lead'].search([]) - leads

    # --- enlazar por referencia de presupuesto ---

    def test_change_citing_an_order_is_posted_on_that_order(self):
        order = self._order()
        leads = self._receive('group_change', 'Cambio en %s' % order.name)
        self.assertFalse(leads)
        self.assertIn('Cambio de comensales', ' '.join(order.message_ids.mapped('body')))
        self.assertFalse(self.env['restagrup.inbox.mail'].search([('name', 'like', order.name)]))

    def test_reference_is_found_in_the_body_too(self):
        order = self._order()
        self._receive('agency_reply', 'Re: propuesta', body='Aceptamos el presupuesto %s' % order.name)
        self.assertIn('Aceptamos el presupuesto', ' '.join(order.message_ids.mapped('body')))

    def test_unknown_reference_goes_to_review(self):
        self._receive('group_change', 'Cambio en S99999')
        self.assertTrue(self.env['restagrup.inbox.mail'].search([('name', 'like', 'S99999')]))

    # --- remitente del sistema ---

    def _sent_from(self, record, trigger):
        trigger()
        message = record.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        return message.email_from

    def _sent_order(self):
        order = self._order()
        order.state = 'sent'
        order.order_line.service_date = fields.Date.context_today(order) + timedelta(days=5)
        return order

    def test_agency_reminder_uses_the_system_sender(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.system_sender', 'sistema@restagrup.example.com')
        order = self._sent_order()
        sender = self._sent_from(order, lambda: order._post_agency_reminder('Asunto', 'Texto', 'agencia-a5@example.com'))
        self.assertIn('sistema@restagrup.example.com', sender)

    def test_agency_reminder_falls_back_to_the_user_without_system_sender(self):
        order = self._sent_order()
        sender = self._sent_from(order, lambda: order._post_agency_reminder('Asunto', 'Texto', 'agencia-a5@example.com'))
        self.assertNotIn('sistema@restagrup.example.com', sender or '')

    def test_restaurant_emails_use_the_system_sender(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.system_sender', 'sistema@restagrup.example.com')
        lead = self.env['crm.lead'].create({'name': 'Grupo remitente'})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 10})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'google', 'name': 'Rest', 'email': 'rest@example.com'})
        sender = self._sent_from(line, lambda: line._post_email('Asunto', 'Texto', 'rest@example.com'))
        self.assertIn('sistema@restagrup.example.com', sender)
