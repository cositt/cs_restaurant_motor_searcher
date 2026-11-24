# -*- coding: utf-8 -*-
"""Reunión 23/11 (5c): «Enviar SdP» (solicitud de presupuesto de compra) se oculta en la hoja del restaurante:
Restagrup pide el presupuesto desde la búsqueda de restaurantes, no desde Compras."""
from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReunion2311Sdp(TransactionCase):

    def _buttons(self):
        arch = self.env['purchase.order'].get_view(view_type='form')['arch']
        return etree.fromstring(arch.encode()).xpath('//button[@name="action_rfq_send"]')

    def test_send_rfq_buttons_are_hidden(self):
        rfq = [b for b in self._buttons() if "'send_rfq':True" in (b.get('context') or '').replace(' ', '')]
        self.assertTrue(rfq)
        for button in rfq:
            self.assertEqual(button.get('invisible'), '1')

    def test_send_purchase_order_button_is_untouched(self):
        po = [b for b in self._buttons() if "'send_rfq':False" in (b.get('context') or '').replace(' ', '')]
        self.assertTrue(po)
        self.assertNotEqual(po[0].get('invisible'), '1')
