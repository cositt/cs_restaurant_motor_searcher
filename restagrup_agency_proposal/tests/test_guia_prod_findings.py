# -*- coding: utf-8 -*-
from collections import namedtuple
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
Attachment = namedtuple('Attachment', ['fname', 'content', 'info'])
VALID_IBAN = 'ES91 2100 0418 4502 0005 1332'


@tagged('post_install', '-at_install')
class TestGuiaProdFindings(TransactionCase):
    """Fallos vistos al probar la guía en producción (2026-10-29): pagos, cuenta y factura del restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        for template in cls.env['restagrup.mail.template'].search([]):
            template.auto_send = False
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia guía F5', 'email': 'guia-f5@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa guía F5', 'is_restaurant': True, 'email': 'guia-casa@example.com'})

    def _order(self, days=5):
        product = self.env['product.template'].create({
            'name': 'Menú guía', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0,
            'sale_ok': True, 'restaurant_id': self.restaurant.id}).product_variant_id
        self.lead = self.env['crm.lead'].create({'name': 'Grupo guía F5', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': self.lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_hour': 14.0,
                                   'service_date': fields.Date.context_today(self.lead) + timedelta(days=days)})]})
        order.action_confirm()
        return order

    def _bank_request(self):
        sheet = self._order().restaurant_po_ids
        sheet.state = 'sent'
        self.env['purchase.order']._cron_restaurant_payments()
        return sheet, self.Queue.search([
            ('purchase_order_id', '=', sheet.id), ('kind', '=', 'restaurant_bank_request')])

    def _iban_reply(self, sheet):
        with patch(LLM_PATH, return_value=({'estado': 'accepted', 'resumen': 'Mandan su cuenta'}, 'groq')) as llm:
            # La respuesta la procesa el buzón, que corre sin idioma (inglés).
            sheet.with_context(lang='en_US').message_update(
                {'body': '<p>Nuestra cuenta: %s</p>' % VALID_IBAN, 'attachments': []})
        return llm

    # --- 11: la cola enseña grupo y restaurante ---

    def test_bank_request_shows_group_and_restaurant(self):
        _sheet, mail = self._bank_request()
        self.assertEqual(mail.group_id, self.lead)
        self.assertEqual(mail.restaurant_name, 'Casa guía F5')

    def test_agency_payment_request_shows_the_group(self):
        order = self._order(days=3)
        self.env['sale.order']._cron_agency_payments()
        mail = self.Queue.search([('sale_order_id', '=', order.id)])
        self.assertTrue(mail)
        self.assertEqual(mail[:1].group_id, self.lead)

    # --- 12: la firma no sale dos veces ---

    def test_bank_request_does_not_add_the_user_signature(self):
        sheet, mail = self._bank_request()
        mail.action_approve()
        message = sheet.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        self.assertTrue(message)
        self.assertFalse(message.email_add_signature)

    # --- 16 y 13: la respuesta con la cuenta no es la respuesta a la hoja ---

    def test_iban_reply_is_not_classified_as_sheet_answer(self):
        sheet, mail = self._bank_request()
        mail.action_approve()
        llm = self._iban_reply(sheet)
        self.assertTrue(sheet.restagrup_has_bank)
        self.assertFalse(sheet.restagrup_response_state)
        llm.assert_not_called()

    def test_saved_account_leaves_no_english_note_on_the_restaurant(self):
        sheet, mail = self._bank_request()
        mail.action_approve()
        self._iban_reply(sheet)
        bodies = ' '.join(str(body) for body in self.restaurant.message_ids.mapped('body'))
        self.assertNotIn('created', bodies)

    def test_invoice_reply_is_not_classified_as_sheet_answer(self):
        sheet = self._order(days=-2).restaurant_po_ids
        sheet.state = 'sent'
        invoice = {'es_factura': True, 'numero': 'F-1', 'fecha': '2026-10-29', 'importe_total': sheet.amount_total,
                   'nif_receptor': None}
        with patch(LLM_PATH, return_value=(invoice, 'groq')) as llm:
            sheet.message_update(
                {'body': '<p>Adjuntamos factura.</p>', 'attachments': [Attachment('F-1.pdf', b'x', {})]})
        self.assertEqual(sheet.restagrup_invoice_proof_state, 'received')
        self.assertFalse(sheet.restagrup_response_state)
        self.assertEqual(llm.call_count, 1, 'solo la lectura de la factura')

    # --- 14: la fecha de la factura se ve como fecha ---

    def test_invoice_date_is_shown_as_a_date(self):
        sheet = self._order(days=-2).restaurant_po_ids
        sheet.restagrup_invoice_date = '2026-10-29'
        self.assertEqual(sheet.restagrup_invoice_date_display, '29/10/2026')
