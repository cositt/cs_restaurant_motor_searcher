# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

VALID_IBAN = 'ES91 2100 0418 4502 0005 1332'
WRONG_IBAN = 'ES91 2100 0418 4502 0005 1333'


@tagged('post_install', '-at_install')
class TestRestaurantPayment(TransactionCase):
    """F5: el pago a cada restaurante. Si no tenemos su cuenta se la pedimos (con la proforma), a las 48 h toca
    pagarle y, hecha la transferencia, se le manda el justificante con nuestros datos fiscales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        for key in ('payment_request_days', 'restaurant_payment_hours'):
            cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.%s' % key)]).unlink()
        for template in cls.env['restagrup.mail.template'].search([]):
            template.auto_send = False
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia F5', 'email': 'f5@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa sin cuenta', 'is_restaurant': True, 'email': 'sin-cuenta@example.com'})
        cls.banked = cls.env['res.partner'].create({
            'name': 'Casa con cuenta', 'is_restaurant': True, 'email': 'con-cuenta@example.com'})
        cls.env['res.partner.bank'].create({'partner_id': cls.banked.id, 'acc_number': 'ES7921000813610123456789'})

    def _sheet(self, days, restaurant=None):
        restaurant = restaurant or self.restaurant
        product = self.env['product.template'].create({
            'name': 'Menú %s' % restaurant.name, 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0,
            'sale_ok': True, 'restaurant_id': restaurant.id}).product_variant_id
        lead = self.env['crm.lead'].create({'name': 'Grupo F5', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_hour': 20.5,
                                   'service_date': fields.Date.context_today(lead) + timedelta(days=days)})]})
        order.action_confirm()
        return order.restaurant_po_ids

    def _cron(self):
        self.env['purchase.order']._cron_restaurant_payments()

    def _mails(self, sheet, kind='restaurant_bank_request'):
        return self.Queue.search([('purchase_order_id', '=', sheet.id), ('kind', '=', kind)])

    def _emails(self, sheet):
        return sheet.message_ids.filtered(lambda m: m.message_type == 'email')

    # --- pedir la cuenta ---

    def test_service_date_of_the_sheet(self):
        sheet = self._sheet(5)
        self.assertEqual(sheet.restagrup_service_date, fields.Date.context_today(sheet) + timedelta(days=5))

    def test_restaurant_without_account_is_asked_for_it(self):
        sheet = self._sheet(5)
        self._cron()
        mail = self._mails(sheet)
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.recipient_email, 'sin-cuenta@example.com')
        self.assertIn('numero de cuenta', mail.body)
        self.assertIn('proforma', mail.body)
        self._cron()
        self.assertEqual(len(self._mails(sheet)), 1, 'una sola vez')

    def test_restaurant_with_account_is_not_asked(self):
        sheet = self._sheet(5, self.banked)
        self._cron()
        self.assertFalse(self._mails(sheet))

    def test_far_paid_or_cancelled_sheets_are_left_alone(self):
        far = self._sheet(12)
        paid = self._sheet(5)
        paid.action_mark_restaurant_paid()
        cancelled = self._sheet(5)
        cancelled.button_cancel()
        self._cron()
        self.assertFalse(self.Queue.search([('purchase_order_id', 'in', (far | paid | cancelled).ids)]))

    def test_approving_sends_it_with_the_proforma(self):
        sheet = self._sheet(5)
        self._cron()
        mail = self._mails(sheet)
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        sent = self._emails(sheet)
        self.assertEqual(sent.outgoing_email_to, 'sin-cuenta@example.com')
        self.assertTrue(sent.attachment_ids.filtered(lambda a: a.name.startswith('Confirmacion-Restaurante')))
        self.assertTrue(sheet.restagrup_bank_request_date)

    def test_once_the_account_exists_the_request_no_longer_applies(self):
        sheet = self._sheet(5)
        self._cron()
        self.env['res.partner.bank'].create({'partner_id': self.restaurant.id, 'acc_number': VALID_IBAN})
        mail = self._mails(sheet)
        mail.action_approve()
        self.assertEqual(mail.state, 'discarded')

    def test_bank_request_can_go_out_on_its_own(self):
        self.env['restagrup.mail.template']._get('restaurant_bank_request').auto_send = True
        sheet = self._sheet(5)
        self._cron()
        self.assertFalse(self._mails(sheet))
        self.assertEqual(len(self._emails(sheet)), 1)

    # --- la cuenta que contesta el restaurante ---

    def _reply(self, sheet, body):
        sheet.restagrup_bank_request_date = fields.Datetime.now()
        sheet.message_update({'body': body, 'attachments': []})

    def test_iban_in_the_reply_is_saved_on_the_restaurant(self):
        sheet = self._sheet(5)
        self._reply(sheet, '<p>Nuestra cuenta: %s. Saludos</p>' % VALID_IBAN)
        self.assertEqual(self.restaurant.bank_ids.acc_number.replace(' ', ''), VALID_IBAN.replace(' ', ''))
        self.assertIn('Cuenta bancaria guardada', ' '.join(sheet.message_ids.mapped('body')))

    def test_wrong_iban_is_not_saved(self):
        sheet = self._sheet(5)
        self._reply(sheet, '<p>IBAN %s</p>' % WRONG_IBAN)
        self.assertFalse(self.restaurant.bank_ids)
        self.assertIn('no es válida', ' '.join(sheet.message_ids.mapped('body')))

    def test_iban_is_only_read_when_we_asked_for_it(self):
        sheet = self._sheet(5)
        sheet.message_update({'body': '<p>%s</p>' % VALID_IBAN, 'attachments': []})
        self.assertFalse(self.restaurant.bank_ids)

    # --- toca pagar ---

    def test_forty_eight_hours_before_the_payment_is_due(self):
        due = self._sheet(1, self.banked)
        later = self._sheet(5, self.banked)
        self._cron()
        self.assertTrue(due.restagrup_payment_due)
        self.assertFalse(later.restagrup_payment_due)
        due.action_mark_restaurant_paid()
        self.assertFalse(due.restagrup_payment_due)

    def test_restaurant_payments_list(self):
        sheet = self._sheet(1, self.banked)
        action = self.env.ref('restagrup_agency_proposal.action_restaurant_payments')
        records = self.env['purchase.order'].search(eval(action.domain))  # noqa: S307 -- dominio propio
        self.assertIn(sheet, records)
        sheet.action_mark_restaurant_paid()
        self.assertNotIn(sheet, self.env['purchase.order'].search(eval(action.domain)))  # noqa: S307

    # --- justificante al restaurante ---

    def test_payment_receipt_mail_has_the_booking_and_our_tax_data(self):
        sheet = self._sheet(1, self.banked)
        sheet.action_mark_restaurant_paid()
        action = sheet.action_send_payment_receipt()
        ctx = action['context']
        self.assertEqual(action['res_model'], 'mail.compose.message')
        attachment = self.env['ir.attachment'].browse(ctx['default_attachment_ids'])
        self.assertTrue(attachment.name.startswith('Confirmacion-Restaurante'))
        body = ctx['default_body']
        self.assertIn('Casa con cuenta', body)
        self.assertIn('Grupo F5', body)
        self.assertIn(self.env.company.name, body)
        self.assertIn('Enviar factura únicamente por email', body)
        self.assertEqual(ctx['default_partner_ids'], self.banked.ids)

    def test_sending_the_receipt_is_recorded(self):
        sheet = self._sheet(1, self.banked)
        sheet.action_mark_restaurant_paid()
        ctx = sheet.action_send_payment_receipt()['context']
        sheet.with_context(ctx).message_post(body='Justificante', message_type='comment')
        self.assertTrue(sheet.restagrup_payment_receipt_sent_date)

    def test_templates_exist(self):
        Template = self.env['restagrup.mail.template']
        self.assertTrue(Template._get('restaurant_bank_request').can_auto_send)
        self.assertFalse(Template._get('restaurant_payment_receipt').can_auto_send, 'lo manda una persona')

    def test_sheet_form_has_the_buttons(self):
        arch = self.env.ref('restagrup_agency_proposal.view_purchase_order_form_close_checklist').get_combined_arch()
        self.assertIn('action_send_payment_receipt', arch)
        self.assertIn('restagrup_payment_due', arch)
