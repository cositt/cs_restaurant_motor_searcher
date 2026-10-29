# -*- coding: utf-8 -*-
from collections import namedtuple
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
Attachment = namedtuple('Attachment', ['fname', 'content', 'info'])


@tagged('post_install', '-at_install')
class TestAgencyPayment(TransactionCase):
    """F4: el pago de la agencia. Se le pide a los 7 días, se le reclama a las 72 h y, cuando manda el justificante,
    la IA lo lee y una persona confirma el pago. Nunca se marca pagado solo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        for key in ('payment_request_days', 'payment_alert_hours'):
            cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.%s' % key)]).unlink()
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia pagos', 'email': 'pagos@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa pagos', 'is_restaurant': True, 'email': 'casa-pagos@example.com'})
        cls.product = cls.env['product.template'].create({
            'name': 'Menú pagos', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id
        for template in cls.env['restagrup.mail.template'].search([]):
            template.auto_send = False

    def _order(self, days, confirm=True):
        lead = self.env['crm.lead'].create({'name': 'Grupo pagos', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 40,
                                   'service_date': fields.Date.context_today(lead) + timedelta(days=days)})]})
        if confirm:
            order.action_confirm()
        return order

    def _mails(self, order, kind):
        return self.Queue.search([('sale_order_id', '=', order.id), ('kind', '=', kind)])

    def _cron(self):
        self.env['sale.order']._cron_agency_payments()

    def _emails(self, order):
        return order.message_ids.filtered(lambda m: m.message_type == 'email')

    # --- pedir el pago ---

    def test_far_service_asks_nothing_yet(self):
        order = self._order(10)
        self._cron()
        self.assertFalse(self.Queue.search([('sale_order_id', '=', order.id)]))

    def test_seven_days_before_the_payment_is_requested(self):
        order = self._order(6)
        self._cron()
        mail = self._mails(order, 'agency_payment_request')
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.recipient_email, 'pagos@example.com')
        self.assertIn('Agencia pagos', mail.body)
        self.assertIn(order.name, mail.body)
        self.assertIn('justificante', mail.body)
        self._cron()
        self.assertEqual(len(self._mails(order, 'agency_payment_request')), 1, 'una sola vez')

    def test_seventy_two_hours_before_it_is_claimed_urgently(self):
        order = self._order(2)
        self._cron()
        self.assertFalse(self._mails(order, 'agency_payment_request'), 'ya no toca la petición normal')
        mail = self._mails(order, 'agency_payment_urgent')
        self.assertEqual(len(mail), 1)
        self.assertIn('proximidad', mail.body)

    def test_after_the_request_comes_the_urgent_claim(self):
        order = self._order(6)
        self._cron()
        self._mails(order, 'agency_payment_request').action_approve()
        self.assertTrue(order.restagrup_payment_requested_date)
        order.order_line.service_date = fields.Date.context_today(order) + timedelta(days=2)
        self._cron()
        self.assertEqual(len(self._mails(order, 'agency_payment_urgent')), 1)

    def test_paid_unconfirmed_or_past_orders_are_left_alone(self):
        paid = self._order(2)
        paid.action_mark_paid()
        quotation = self._order(2, confirm=False)
        past = self._order(-1)
        self._cron()
        self.assertFalse(self.Queue.search([('sale_order_id', 'in', (paid | quotation | past).ids)]))

    def test_approving_sends_it_on_the_order_thread(self):
        order = self._order(6)
        self._cron()
        mail = self._mails(order, 'agency_payment_request')
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        self.assertEqual(self._emails(order).outgoing_email_to, 'pagos@example.com')

    def test_a_request_that_no_longer_applies_is_discarded(self):
        order = self._order(6)
        self._cron()
        mail = self._mails(order, 'agency_payment_request')
        order.action_mark_paid()
        mail.action_approve()
        self.assertEqual(mail.state, 'discarded')
        self.assertFalse(self._emails(order))

    def test_it_can_go_out_on_its_own(self):
        self.env['restagrup.mail.template']._get('agency_payment_urgent').auto_send = True
        order = self._order(2)
        self._cron()
        self.assertFalse(self._mails(order, 'agency_payment_urgent'))
        self.assertEqual(len(self._emails(order)), 1)
        self.assertTrue(order.restagrup_payment_urgent_date)

    def test_texts_are_editable_templates(self):
        Template = self.env['restagrup.mail.template']
        for code in ('agency_payment_request', 'agency_payment_urgent'):
            template = Template._get(code)
            self.assertTrue(template, code)
            self.assertEqual(template.recipient, 'agency')
            self.assertTrue(template.can_auto_send)
        Template._get('agency_payment_request').body = 'Pago de {agencia} para {pedido}, por favor.'
        order = self._order(6)
        self._cron()
        self.assertEqual(self._mails(order, 'agency_payment_request').body,
                         'Pago de Agencia pagos para %s, por favor.' % order.name)

    def test_text_written_in_settings_moves_to_its_template(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.payment_urgent_text', 'Urgente {agencia}.')
        Template = self.env['restagrup.mail.template']
        Template._import_payment_texts()
        self.assertIn('Urgente {agencia}.', Template._get('agency_payment_urgent').body)
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param('restagrup.payment_urgent_text'))

    # --- el justificante ---

    def _reply(self, record, data, attachments=None, body='<p>Os adjuntamos el justificante.</p>'):
        with patch(LLM_PATH, return_value=(data, 'groq')) as llm:
            record.message_update({'body': body, 'attachments': attachments or []})
        return llm

    def test_a_receipt_is_read_and_left_for_a_person_to_confirm(self):
        order = self._order(5)
        self._reply(order, {'es_justificante': True, 'importe': order.amount_total, 'fecha': '2026-10-28',
                            'referencia': 'TRF-1'}, attachments=[Attachment('justificante.pdf', b'x', {})])
        self.assertEqual(order.restagrup_payment_proof_state, 'received')
        self.assertEqual(order.restagrup_payment_proof_amount, order.amount_total)
        self.assertEqual(order.restagrup_payment_proof_name, 'justificante.pdf')
        self.assertFalse(order.restagrup_paid, 'nunca se marca pagado solo')
        self.assertIn('Justificante de pago recibido', ' '.join(order.message_ids.mapped('body')))

    def test_confirming_the_receipt_marks_the_order_paid(self):
        order = self._order(5)
        self._reply(order, {'es_justificante': True, 'importe': order.amount_total})
        order.action_confirm_payment_proof()
        self.assertTrue(order.restagrup_paid)
        self.assertFalse(order.restagrup_payment_proof_state)

    def test_a_wrong_receipt_can_be_discarded(self):
        order = self._order(5)
        self._reply(order, {'es_justificante': True, 'importe': 10.0})
        order.action_discard_payment_proof()
        self.assertFalse(order.restagrup_paid)
        self.assertFalse(order.restagrup_payment_proof_state)

    def test_a_different_amount_is_warned(self):
        order = self._order(5)
        self._reply(order, {'es_justificante': True, 'importe': 10.0})
        self.assertEqual(order.restagrup_payment_proof_state, 'received')
        self.assertIn('no coincide', ' '.join(order.message_ids.mapped('body')))

    def test_a_reply_that_is_not_a_receipt_changes_nothing(self):
        order = self._order(5)
        self._reply(order, {'es_justificante': False})
        self.assertFalse(order.restagrup_payment_proof_state)

    def test_paid_orders_do_not_ask_the_ai(self):
        order = self._order(5)
        order.action_mark_paid()
        llm = self._reply(order, {'es_justificante': True, 'importe': 1.0})
        llm.assert_not_called()

    def test_quotations_do_not_ask_the_ai(self):
        order = self._order(5, confirm=False)
        llm = self._reply(order, {'es_justificante': True, 'importe': 1.0})
        llm.assert_not_called()

    def test_receipt_sent_to_the_group_goes_to_its_unpaid_order(self):
        order = self._order(5)
        self._reply(order.opportunity_id, {'es_justificante': True, 'importe': order.amount_total},
                    attachments=[Attachment('transferencia.jpg', b'img', {})])
        self.assertEqual(order.restagrup_payment_proof_state, 'received')
        self.assertEqual(order.restagrup_payment_proof_name, 'transferencia.jpg')

    def test_the_ai_sees_the_attachment_names_and_pdf_text(self):
        order = self._order(5)
        llm = self._reply(order, {'es_justificante': False},
                          attachments=[Attachment('justificante.pdf', b'no es un pdf', {})])
        self.assertIn('justificante.pdf', llm.call_args.args[1])

    # --- en pantalla ---

    def test_order_form_shows_the_receipt_and_its_buttons(self):
        arch = self.env.ref('restagrup_agency_proposal.view_order_form_payment_deadlines').get_combined_arch()
        for name in ('restagrup_payment_proof_state', 'action_confirm_payment_proof', 'action_discard_payment_proof'):
            self.assertIn(name, arch)
