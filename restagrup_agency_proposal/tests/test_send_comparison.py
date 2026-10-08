# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSendComparison(TransactionCase):
    """Envío de la comparativa al cliente: siempre el PDF; el enlace de portal solo si se pide."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://demo.example.com')
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Grupo Whitfield', 'email_from': 'Eleanor <eleanor@cliente.example>',
        })
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 32,
        })
        partner = cls.env['res.partner'].create({'name': 'Casa A', 'is_restaurant': True})
        cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': 'Casa A', 'partner_id': partner.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 1000.0,
        })

    def _wizard(self, **extra):
        vals = {'search_id': self.search.id}
        vals.update(extra)
        return self.env['restagrup.client.comparison.wizard'].create(vals)

    def _last_message(self):
        return self.lead.message_ids.filtered(lambda m: m.message_type == 'email')[:1]

    def test_defaults_come_from_the_lead(self):
        wizard = self._wizard()
        self.assertEqual(wizard.email_to, 'eleanor@cliente.example')
        self.assertIn('Málaga', wizard.subject)
        self.assertFalse(wizard.include_portal_link)

    def test_sends_only_the_pdf_by_default(self):
        self._wizard().action_send()
        message = self._last_message()
        self.assertTrue(message)
        self.assertEqual(message.outgoing_email_to, 'eleanor@cliente.example')
        self.assertEqual(message.attachment_ids.mapped('mimetype'), ['application/pdf'])
        self.assertNotIn('comparativa/', message.body)
        self.assertFalse(self.search.comparison_token)

    def test_portal_link_is_added_only_when_requested(self):
        self._wizard(include_portal_link=True).action_send()
        message = self._last_message()
        self.assertTrue(self.search.comparison_token)
        self.assertIn('https://demo.example.com/comparativa/%s/%s' % (self.search.id, self.search.comparison_token),
                      message.body)
        self.assertEqual(len(message.attachment_ids), 1)  # el PDF va igualmente

    def test_portal_token_is_reused_between_sends(self):
        self._wizard(include_portal_link=True).action_send()
        first = self.search.comparison_token
        self._wizard(include_portal_link=True).action_send()
        self.assertEqual(self.search.comparison_token, first)

    def test_needs_a_recipient(self):
        with self.assertRaises(UserError):
            self._wizard(email_to=False).action_send()

    def test_needs_at_least_one_confirmed_quote(self):
        self.search.line_ids.write({'etiqueta': 'solicitado'})
        with self.assertRaises(UserError):
            self._wizard().action_send()

    def test_sending_the_comparison_moves_the_group_to_presupuesto(self):
        stage = self.env.ref('restagrup_service_orders.stage_presupuesto')
        self._wizard().action_send()
        self.assertEqual(self.lead.stage_id, stage)

    def test_sending_again_does_not_move_a_group_that_is_already_further(self):
        self.lead.with_context(restagrup_skip_firewall=True).action_pass_to_file()
        self._wizard().action_send()
        self.assertEqual(self.lead.stage_id, self.env.ref('restagrup_service_orders.stage_expediente'))
