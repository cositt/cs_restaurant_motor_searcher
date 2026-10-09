# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'
WIZARD = 'restagrup.firewall.wizard'


@tagged('post_install', '-at_install')
class TestReviewPoints(TransactionCase):
    """Puntos de revisión: antes de escribir al restaurante, el sistema enseña qué va a enviar y a quién, y una
    persona lo revisa. RestaGrup puede desactivar cada punto cuando coja confianza."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia revisión', 'email': 'ag-rev@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo revisión', 'partner_id': cls.agency.id})
        cls.rest_a = cls.env['res.partner'].create({
            'name': 'Casa Uno', 'is_restaurant': True, 'email': 'uno@example.com'})
        cls.rest_b = cls.env['res.partner'].create({
            'name': 'Casa Dos', 'is_restaurant': True, 'email': 'dos@example.com'})
        cls.reason = cls.env.ref('restagrup_core.cancel_reason_cheaper')
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'pax': 40, 'event_date': '2026-11-15',
            'event_type_id': cls.env.ref('restagrup_core.event_type_dinner').id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Málaga', 'min_capacity': 40})
        cls.line_a = cls._quote(cls.search, cls.rest_a, 1000)
        cls.line_b = cls._quote(cls.search, cls.rest_b, 800)
        cls.line_a.action_toggle_chosen()
        cls.search.action_create_sale_order()
        cls.order = cls.search.sale_order_id

    @classmethod
    def _quote(cls, search, restaurant, amount):
        return cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': amount})

    def _check(self, code='review_restaurant_notice'):
        return self.env['restagrup.firewall.check'].with_context(active_test=False).search([('code', '=', code)])

    def _notices(self):
        return self.env['restagrup.restaurant.notice'].search([('lead_id', '=', self.lead.id)])

    def _notice_wizard(self):
        wizard = self.lead._create_notice_wizard()
        wizard.write({'subject': 'Cambio de comensales', 'body': '<p>Hola {restaurante}</p>'})
        return wizard

    # --- la comprobación existe y es de revisión ---

    def test_review_checks_exist_active_in_warning_mode(self):
        for code in ('review_restaurant_notice', 'review_proposal'):
            check = self._check(code)
            self.assertTrue(check, code)
            self.assertTrue(check.active, code)
            self.assertTrue(check.is_review, code)
            self.assertEqual(check.mode, 'warn', code)

    # --- aviso a restaurantes ---

    def test_notice_shows_the_review_before_sending(self):
        action = self._notice_wizard().action_send()
        self.assertEqual(action['res_model'], WIZARD)
        self.assertFalse(self._notices(), 'no se envía nada hasta que una persona lo revisa')
        wizard = self.env[WIZARD].browse(action['res_id'])
        self.assertTrue(wizard.is_review)
        self.assertIn('Casa Uno', wizard.message)
        self.assertIn('uno@example.com', wizard.message)
        self.assertIn('Cambio de comensales', wizard.message)

    def test_continuing_after_the_review_sends_and_leaves_a_note(self):
        action = self._notice_wizard().action_send()
        self.env[WIZARD].browse(action['res_id']).action_continue()
        self.assertTrue(self._notices())
        self.assertTrue(self.lead.message_ids.filtered(lambda m: 'revisado' in (m.body or '')))

    def test_going_back_sends_nothing(self):
        action = self._notice_wizard().action_send()
        self.env[WIZARD].browse(action['res_id']).action_cancel()
        self.assertFalse(self._notices())

    def test_switching_the_check_off_sends_directly(self):
        self._check().active = False
        self._notice_wizard().action_send()
        self.assertTrue(self._notices())

    def test_skip_context_sends_directly(self):
        self._notice_wizard().with_context(restagrup_skip_firewall=True).action_send()
        self.assertTrue(self._notices())

    def test_review_never_blocks_even_if_set_to_block(self):
        self._check().mode = 'block'
        action = self._notice_wizard().action_send()
        self.assertEqual(action['res_model'], WIZARD)

    # --- cambio de restaurante ---

    def test_change_of_restaurant_is_reviewed_before_anything_changes(self):
        wizard = self.env['restagrup.restaurant.change.wizard'].create({
            'search_id': self.search.id, 'reason_id': self.reason.id, 'notify_restaurant': True,
            'subject': 'Cancelación', 'body': '<p>Cancelamos la petición</p>',
            'replacement_line_id': self.line_b.id})
        action = wizard.action_confirm()
        self.assertEqual(action['res_model'], WIZARD)
        self.assertEqual(self.line_a.etiqueta, 'presupuesto_recibido')
        self.assertEqual(self.search.chosen_line_id, self.line_a)
        review = self.env[WIZARD].browse(action['res_id'])
        self.assertIn('Casa Uno', review.message)
        self.assertIn('Casa Dos', review.message)
        review.action_continue()
        self.assertEqual(self.line_a.etiqueta, 'cancelado')
        self.assertEqual(self.search.chosen_line_id, self.line_b)

    def test_change_without_notice_has_nothing_to_review(self):
        wizard = self.env['restagrup.restaurant.change.wizard'].create({
            'search_id': self.search.id, 'reason_id': self.reason.id, 'notify_restaurant': False})
        self.assertNotEqual(wizard.action_confirm().get('res_model'), WIZARD)
        self.assertEqual(self.line_a.etiqueta, 'cancelado')

    # --- reenviar cambios ---

    def test_resending_changes_is_reviewed_before_mailing_the_restaurant(self):
        self.order.order_line.service_date = date(2026, 12, 15)
        self.order.action_confirm()
        self.order.with_context(restagrup_skip_firewall=True).action_send_restaurant_orders()
        po = self.order.sudo().restaurant_po_ids
        po.restagrup_response_state = 'accepted'
        self.order.order_line.write({'product_uom_qty': 45})
        action = self.order.action_resend_restaurant_orders()
        self.assertEqual(action['res_model'], WIZARD)
        review = self.env[WIZARD].browse(action['res_id'])
        self.assertIn('Casa Uno', review.message)
        mails_before = self.env['mail.mail'].search_count([('model', '=', 'purchase.order'), ('res_id', '=', po.id)])
        review.action_continue()
        mails_after = self.env['mail.mail'].search_count([('model', '=', 'purchase.order'), ('res_id', '=', po.id)])
        self.assertGreater(mails_after, mails_before)
