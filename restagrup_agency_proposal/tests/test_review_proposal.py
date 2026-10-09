# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

WIZARD = 'restagrup.firewall.wizard'
COMPARISON = 'restagrup.client.comparison.wizard'


@tagged('post_install', '-at_install')
class TestReviewProposal(TransactionCase):
    """Antes de enviar la propuesta a la agencia, una persona revisa restaurantes, precios y condiciones."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia propuesta', 'email': 'ag-prop@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo propuesta', 'partner_id': cls.agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Sevilla', 'min_capacity': 30})
        for name, amount in (('Casa Barata', 900.0), ('Casa Cara', 1500.0)):
            restaurant = cls.env['res.partner'].create({
                'name': name, 'is_restaurant': True, 'email': '%s@example.com' % name[:4].lower()})
            cls.env['restagrup.restaurant.search.line'].create({
                'search_id': cls.search.id, 'source': 'partner', 'name': name, 'partner_id': restaurant.id,
                'etiqueta': 'presupuesto_recibido', 'quote_amount': amount})
        cls.search.min_capacity = 30

    def _wizard(self):
        return self.env[COMPARISON].create({'search_id': self.search.id, 'email_to': 'ag-prop@example.com'})

    def _check(self):
        return self.env['restagrup.firewall.check'].with_context(active_test=False).search(
            [('code', '=', 'review_proposal')])

    def _sent(self):
        return self.lead.message_ids.filtered(lambda m: m.message_type == 'email' and m.outgoing_email_to)

    def test_sending_the_proposal_shows_the_review_first(self):
        action = self._wizard().action_send()
        self.assertEqual(action['res_model'], WIZARD)
        self.assertFalse(self._sent())
        review = self.env[WIZARD].browse(action['res_id'])
        self.assertTrue(review.is_review)
        for text in ('ag-prop@example.com', 'Casa Barata', 'Casa Cara', 'por persona'):
            self.assertIn(text, review.message)

    def test_review_states_whether_restaurant_names_are_shown(self):
        self.search.restaurant_visible = False
        review = self.env[WIZARD].browse(self._wizard().action_send()['res_id'])
        self.assertIn('Opción 1', review.message)
        self.assertNotIn('Casa Barata', review.message)

    def test_continuing_sends_the_email_and_moves_the_group_to_quote(self):
        review = self.env[WIZARD].browse(self._wizard().action_send()['res_id'])
        review.action_continue()
        self.assertTrue(self._sent())
        self.assertEqual(self.lead.restagrup_stage_key, 'presupuesto')

    def test_switching_the_review_off_sends_directly(self):
        self._check().active = False
        self._wizard().action_send()
        self.assertTrue(self._sent())
