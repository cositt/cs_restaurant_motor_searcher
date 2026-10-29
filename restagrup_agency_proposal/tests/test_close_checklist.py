# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

CLOSE_CODES = {'paid', 'restaurant_paid', 'agency_invoice_sent', 'restaurant_invoice'}


@tagged('post_install', '-at_install')
class TestCloseChecklist(TransactionCase):
    """Para cerrar un expediente: pago de la agencia, transferencia al restaurante, factura a la agencia y factura del
    restaurante recibida y revisada. El grupo enseña qué falta."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia cierre', 'email': 'cierre@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa cierre', 'is_restaurant': True, 'email': 'casa-cierre@example.com'})
        cls.product = cls.env['product.template'].create({
            'name': 'Menú cierre', 'type': 'service', 'standard_price': 30.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id
        cls.expediente = cls.env['crm.stage'].search([('restagrup_stage_key', '=', 'expediente')], limit=1)
        cls.cerrado = cls.env['crm.stage'].search([('restagrup_stage_key', '=', 'cerrado')], limit=1)

    def _group(self, days_ago=2):
        lead = self.env['crm.lead'].create({
            'name': 'Grupo cierre', 'partner_id': self.agency.id, 'stage_id': self.expediente.id})
        service = fields.Date.context_today(lead) - timedelta(days=days_ago)
        self.env['restagrup.lead.event'].create({'lead_id': lead.id, 'city': 'Málaga', 'pax': 40, 'event_date': service})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 40, 'service_date': service})]})
        order.action_confirm()
        return lead, order, order.restaurant_po_ids

    def _complete(self, order, sheets):
        order.action_mark_paid()
        order.action_mark_invoice_sent()
        sheets.action_mark_restaurant_paid()
        sheets.action_mark_invoice_received()

    def _codes(self, lead):
        return {issue['check'].code for issue in lead._restagrup_firewall_issues('close_file')}

    # --- qué falta ---

    def test_new_expediente_misses_the_four_steps(self):
        lead, _order, _sheets = self._group()
        self.assertTrue(CLOSE_CODES <= self._codes(lead))
        pending = lead.restagrup_close_pending
        for label in ('Pago de la agencia', 'Transferencia al restaurante', 'Factura a la agencia',
                      'Factura del restaurante'):
            self.assertIn(label, pending)
        self.assertFalse(lead.restagrup_close_ready)

    def test_each_step_marked_disappears_from_what_is_missing(self):
        lead, order, sheets = self._group()
        order.action_mark_paid()
        self.assertTrue(lead.restagrup_close_agency_paid)
        self.assertNotIn('Pago de la agencia', lead.restagrup_close_pending)
        sheets.action_mark_restaurant_paid()
        self.assertNotIn('Transferencia al restaurante', lead.restagrup_close_pending)
        order.action_mark_invoice_sent()
        self.assertNotIn('Factura a la agencia', lead.restagrup_close_pending)
        sheets.action_mark_invoice_received()
        self.assertFalse(lead.restagrup_close_pending)
        self.assertTrue(lead.restagrup_close_ready)
        self.assertFalse(CLOSE_CODES & self._codes(lead))

    def test_marks_keep_who_and_when_and_can_be_undone(self):
        _lead, order, sheets = self._group()
        order.action_mark_invoice_sent()
        self.assertTrue(order.restagrup_invoice_sent_date)
        sheets.action_mark_restaurant_paid()
        sheets.action_mark_invoice_received()
        self.assertTrue(sheets.restagrup_restaurant_paid_date)
        self.assertTrue(sheets.restagrup_invoice_received_date)
        self.assertIn('Factura del restaurante recibida', ' '.join(sheets.message_ids.mapped('body')))
        order.action_unmark_invoice_sent()
        sheets.action_unmark_restaurant_paid()
        sheets.action_unmark_invoice_received()
        self.assertFalse(order.restagrup_invoice_sent or sheets.restagrup_restaurant_paid
                         or sheets.restagrup_invoice_received)

    def test_every_restaurant_counts(self):
        lead, order, sheets = self._group()
        other = self.env['res.partner'].create({'name': 'Otra casa', 'is_restaurant': True, 'email': 'o@example.com'})
        product = self.env['product.template'].create({
            'name': 'Menú otra', 'type': 'service', 'standard_price': 20.0, 'sale_ok': True,
            'restaurant_id': other.id}).product_variant_id
        second = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 40})]})
        second.action_confirm()
        self._complete(order, sheets)
        self.assertIn('Otra casa', ' '.join(issue['message'] for issue in lead._restagrup_firewall_issues('close_file')))
        self._complete(second, second.restaurant_po_ids)
        self.assertTrue(lead.restagrup_close_ready)

    def test_cancelled_sheets_do_not_count(self):
        lead, order, sheets = self._group()
        self._complete(order, sheets)
        extra = sheets.copy()
        extra.button_cancel()
        self.assertTrue(lead.restagrup_close_ready)

    def test_without_a_confirmed_order_nothing_is_ready(self):
        lead = self.env['crm.lead'].create({'name': 'Sin pedido', 'stage_id': self.expediente.id})
        self.assertFalse(lead.restagrup_close_ready)
        self.assertTrue(lead.restagrup_close_pending)

    # --- cerrar ---

    def test_closing_is_blocked_until_everything_is_done(self):
        lead, order, sheets = self._group()
        with self.assertRaises(UserError):
            lead.action_close_file()
        self.assertEqual(lead.stage_id, self.expediente)
        self._complete(order, sheets)
        lead.action_close_file()
        self.assertEqual(lead.stage_id, self.cerrado)

    def test_new_checks_block_by_default_and_can_be_relaxed(self):
        checks = self.env['restagrup.firewall.check'].search([
            ('code', 'in', ['restaurant_paid', 'agency_invoice_sent', 'restaurant_invoice'])])
        self.assertEqual(len(checks), 3)
        self.assertEqual(set(checks.mapped('mode')), {'block'})
        self.assertEqual(set(checks.mapped('trigger')), {'close_file'})

    # --- en pantalla ---

    def test_files_list_shows_what_is_missing_to_close(self):
        arch = self.env.ref('restagrup_service_orders.view_crm_lead_restagrup_list').get_combined_arch()
        self.assertIn('restagrup_close_pending', arch)

    def test_team_can_mark_the_steps(self):
        user = self.env['res.users'].create({
            'name': 'Comercial cierre', 'login': 'comercial_cierre',
            'group_ids': [(6, 0, [self.env.ref('sales_team.group_sale_salesman_all_leads').id,
                                  self.env.ref('purchase.group_purchase_user').id])]})
        _lead, order, sheets = self._group()
        order.with_user(user).action_mark_invoice_sent()
        sheets.with_user(user).action_mark_invoice_received()
        self.assertTrue(order.restagrup_invoice_sent and sheets.restagrup_invoice_received)
