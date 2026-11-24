# -*- coding: utf-8 -*-
"""Conchita 24/11: contactar con los restaurantes por WhatsApp desde la tarjeta.
Reutiliza el módulo cositt_quick_whatsapp (wa.me con el número normalizado)."""
from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReunion2411Whatsapp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo WhatsApp'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 30})

    def _line(self, **vals):
        values = {'search_id': self.search.id, 'source': 'google', 'name': 'Casa Test'}
        values.update(vals)
        return self.env['restagrup.restaurant.search.line'].create(values)

    # --- acción ---

    def test_opens_wa_me_with_the_card_phone(self):
        line = self._line(phone='+34 600 111 222')
        action = line.action_open_whatsapp()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], 'https://wa.me/34600111222')
        self.assertEqual(action['target'], 'new')

    def test_works_for_google_results_without_contact(self):
        line = self._line(source='google', phone='0034611222333', partner_id=False)
        self.assertEqual(line.action_open_whatsapp()['url'], 'https://wa.me/34611222333')

    def test_without_phone_raises_a_clear_error(self):
        line = self._line(phone=False)
        with self.assertRaises(UserError):
            line.action_open_whatsapp()

    def test_several_numbers_raise_instead_of_a_broken_link(self):
        line = self._line(phone='91 123 45 67 / 611 222 333')
        with self.assertRaises(UserError):
            line.action_open_whatsapp()

    # --- vista ---

    def test_card_has_a_whatsapp_button_shown_only_with_phone(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        root = etree.fromstring(arch.encode())
        buttons = root.xpath('//button[@name="action_open_whatsapp"] | //a[@name="action_open_whatsapp"]')
        self.assertTrue(buttons, 'la tarjeta debe llevar el botón de WhatsApp')
        self.assertIn('phone', buttons[0].get('t-if') or '')
