# -*- coding: utf-8 -*-
"""Ronda 20/11 (1a): un restaurante de Google sin email no bloquea el envío; se escribe en la ventana."""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRonda2011NoEmail(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lead = cls.env['crm.lead'].create({'name': 'Grupo sin email 2011'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Toledo', 'min_capacity': 30})
        cls.google = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'google', 'name': 'Sabor Test 2011', 'etiqueta': 'interesado'})

    def _wizard(self, action):
        return self.env[action['res_model']].browse(action['res_id'])

    def test_card_without_email_opens_the_window_instead_of_blocking(self):
        wizard = self._wizard(self.google.action_open_quote_request())
        self.assertFalse(wizard.recipient_ids)
        self.assertFalse(wizard.extra_emails)

    def test_window_without_any_email_refuses_to_send(self):
        wizard = self._wizard(self.google.action_open_quote_request())
        with self.assertRaises(UserError):
            wizard.action_send()

    def test_typed_email_is_sent_and_kept_on_the_card(self):
        wizard = self._wizard(self.google.action_open_quote_request())
        wizard.extra_emails = 'reservas@sabor-test.example'
        wizard.action_send()
        self.assertEqual(self.google.etiqueta, 'solicitado')
        self.assertEqual(self.google.email, 'reservas@sabor-test.example')

    def test_bulk_with_a_single_interested_without_email_opens_its_window(self):
        action = self.search.action_request_quote_interested()
        self.assertEqual(action['res_model'], 'restagrup.send.wizard')
        wizard = self._wizard(action)
        wizard.extra_emails = 'reservas@sabor-test.example'
        wizard.action_send()
        self.assertEqual(self.google.email, 'reservas@sabor-test.example')

    def test_bulk_with_several_without_email_explains_how_to_continue(self):
        self.env[LINE].create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Jovi Test 2011', 'etiqueta': 'interesado'})
        with self.assertRaises(UserError) as error:
            self.search.action_request_quote_interested()
        text = str(error.exception)
        self.assertIn('Sabor Test 2011', text)
        self.assertIn('Otros emails', text)

    def test_reminders_still_need_an_email(self):
        with self.assertRaises(UserError):
            self.google._get_quote_email_to()
