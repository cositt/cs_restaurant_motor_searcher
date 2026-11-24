# -*- coding: utf-8 -*-
"""Reunión 23/11: al pedir presupuesto a varios interesados, el Chatter lleva UN mensaje claro con a cuántos
restaurantes y a cuáles (con su email) y el asunto y el texto una sola vez, en vez de una copia por restaurante.
Cada restaurante conserva su correo completo en su propia conversación."""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReunion2311BulkChatter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo chatter masivo'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 30})

    def _line(self, name, email):
        return self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'google', 'name': name, 'etiqueta': 'interesado', 'email': email})

    def _send_all(self):
        action = self.search.action_request_quote_interested()
        return self.env[action['res_model']].browse(action['res_id']).action_send()

    def _search_notes(self):
        return self.search.message_ids.filtered(lambda m: m.message_type == 'notification')

    def test_bulk_posts_one_summary_with_every_restaurant_and_email(self):
        self._line('Casa Uno', 'uno@example.com')
        self._line('Casa Dos', 'dos@example.com')
        self._line('Casa Tres', 'tres@example.com')
        self._send_all()
        bodies = self._search_notes().mapped('body')
        summaries = [b for b in bodies if 'Presupuesto pedido a 3' in b]
        self.assertEqual(len(summaries), 1)
        for text in ('Casa Uno', 'uno@example.com', 'Casa Dos', 'dos@example.com', 'Casa Tres', 'tres@example.com',
                     'Presupuesto para grupos'):
            self.assertIn(text, summaries[0])

    def test_bulk_does_not_repeat_the_whole_email_per_restaurant(self):
        self._line('Casa Uno', 'uno@example.com')
        self._line('Casa Dos', 'dos@example.com')
        self._send_all()
        copies = [b for b in self._search_notes().mapped('body') if 'Presupuesto solicitado a' in b]
        self.assertEqual(copies, [])

    def test_each_restaurant_keeps_its_own_email_in_its_conversation(self):
        first = self._line('Casa Uno', 'uno@example.com')
        second = self._line('Casa Dos', 'dos@example.com')
        self._send_all()
        for line, email in ((first, 'uno@example.com'), (second, 'dos@example.com')):
            sent = line.message_ids.filtered(lambda m: m.message_type == 'email')
            self.assertEqual(sent.mapped('outgoing_email_to'), [email])

    def test_single_request_still_logs_the_text_in_the_chatter(self):
        line = self._line('Casa Uno', 'uno@example.com')
        line.action_request_quote()
        bodies = ' '.join(self._search_notes().mapped('body'))
        self.assertIn('Presupuesto solicitado a Casa Uno', bodies)
