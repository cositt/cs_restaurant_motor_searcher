# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBulkQuoteRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo interesados'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 30,
        })

    def _line(self, name, **vals):
        return self.env['restagrup.restaurant.search.line'].create(
            dict({'search_id': self.search.id, 'source': 'google', 'name': name}, **vals))

    def test_interested_count_counts_only_interesado(self):
        self._line('A', etiqueta='interesado')
        self._line('B', etiqueta='interesado')
        self._line('C', etiqueta='visto')
        self.assertEqual(self.search.interested_count, 2)

    def test_requests_quote_to_every_interested_line(self):
        first = self._line('A', etiqueta='interesado', email='a@example.com')
        second = self._line('B', etiqueta='interesado', email='b@example.com')
        untouched = self._line('C', etiqueta='visto', email='c@example.com')
        self.search.action_request_quote_interested()
        self.assertEqual((first | second).mapped('etiqueta'), ['solicitado', 'solicitado'])
        self.assertEqual(untouched.etiqueta, 'visto')
        sent = (first | second).message_ids.filtered(lambda m: m.message_type == 'email')
        self.assertEqual(sorted(sent.mapped('outgoing_email_to')), ['a@example.com', 'b@example.com'])

    def test_lines_without_email_are_skipped_and_stay_interested(self):
        with_email = self._line('A', etiqueta='interesado', email='a@example.com')
        without_email = self._line('Sin correo', etiqueta='interesado', email=False)
        result = self.search.action_request_quote_interested()
        self.assertEqual(with_email.etiqueta, 'solicitado')
        self.assertEqual(without_email.etiqueta, 'interesado')
        self.assertIn('Sin correo', result['params']['message'])
        self.assertEqual(result['params']['type'], 'warning')

    def test_summary_is_logged_on_the_search(self):
        self._line('A', etiqueta='interesado', email='a@example.com')
        self._line('Sin correo', etiqueta='interesado', email=False)
        self.search.action_request_quote_interested()
        bodies = ' '.join(self.search.message_ids.mapped('body'))
        self.assertIn('Presupuesto pedido a 1 restaurante', bodies)
        self.assertIn('Sin correo', bodies)

    def test_all_sent_returns_success_notification(self):
        self._line('A', etiqueta='interesado', email='a@example.com')
        result = self.search.action_request_quote_interested()
        self.assertEqual(result['params']['type'], 'success')

    def test_no_interested_lines_raises(self):
        self._line('C', etiqueta='visto', email='c@example.com')
        with self.assertRaises(UserError):
            self.search.action_request_quote_interested()

    def test_none_with_email_raises_and_sends_nothing(self):
        line = self._line('Sin correo', etiqueta='interesado', email=False)
        with self.assertRaises(UserError):
            self.search.action_request_quote_interested()
        self.assertEqual(line.etiqueta, 'interesado')
