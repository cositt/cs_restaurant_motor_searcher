# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestChangeRestaurant(TransactionCase):
    """Cancelar o cambiar el restaurante elegido de un evento. Asunto entre Restagrup y el restaurante:
    la agencia no interviene ni recibe nada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env['res.partner'].create({'name': 'Agencia cambio', 'email': 'ag@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo cambio', 'partner_id': cls.client.id})
        cls.rest_a = cls.env['res.partner'].create({'name': 'Casa A', 'is_restaurant': True, 'email': 'a@example.com'})
        cls.rest_b = cls.env['res.partner'].create({'name': 'Casa B', 'is_restaurant': True, 'email': 'b@example.com'})
        cls.rest_c = cls.env['res.partner'].create({'name': 'Casa C', 'is_restaurant': True, 'email': 'c@example.com'})
        cls.reason = cls.env.ref('restagrup_core.cancel_reason_cheaper')

    def _search(self, city='Málaga', type_xmlid='restagrup_core.event_type_dinner', date='2026-11-15', pax=42):
        event = self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': city, 'pax': pax, 'event_date': date,
            'event_type_id': self.env.ref(type_xmlid).id})
        return self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'event_id': event.id, 'city': city, 'min_capacity': pax})

    def _quote(self, search, restaurant, amount, state='presupuesto_recibido'):
        return self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': state, 'quote_amount': amount})

    def _scenario(self, confirm=False):
        """Evento con A elegido (1000 €), B con presupuesto (800 €) y C (900 €); presupuesto de venta creado."""
        search = self._search()
        self.line_a = self._quote(search, self.rest_a, 1000)
        self.line_b = self._quote(search, self.rest_b, 800)
        self.line_c = self._quote(search, self.rest_c, 900)
        self.line_a.action_toggle_chosen()
        search.action_create_sale_order()
        self.order = search.sale_order_id
        if confirm:
            self.order.action_confirm()
        return search

    def _change(self, search, replacement=None, **vals):
        defaults = {'search_id': search.id, 'reason_id': self.reason.id, 'notify_restaurant': False,
                    'replacement_line_id': replacement.id if replacement else False}
        defaults.update(vals)
        wizard = self.env['restagrup.restaurant.change.wizard'].create(defaults)
        wizard.action_confirm()
        return wizard

    # --- cancelar ---

    def test_cancelled_line_keeps_reason_note_and_date_and_is_no_longer_chosen(self):
        search = self._scenario()
        self._change(search, note='No tiene sitio')
        self.assertEqual(self.line_a.etiqueta, 'cancelado')
        self.assertEqual(self.line_a.cancel_reason_id, self.reason)
        self.assertEqual(self.line_a.cancel_note, 'No tiene sitio')
        self.assertTrue(self.line_a.cancelled_date)
        self.assertFalse(search.chosen_line_id)

    def test_cancelled_restaurant_cannot_be_chosen_again_nor_listed_as_quoted(self):
        search = self._scenario()
        self._change(search)
        with self.assertRaises(UserError):
            self.line_a.action_toggle_chosen()
        self.assertNotIn(self.line_a, search.quoted_line_ids)

    def test_cancel_without_replacement_removes_the_line_from_an_unsigned_order(self):
        search = self._scenario()
        self._change(search)
        self.assertFalse(self.order.order_line)
        self.assertEqual(search.pipeline_stage, 'quotes_received')

    def test_reasons_are_loaded(self):
        names = self.env['restagrup.cancel.reason'].search([]).mapped('name')
        self.assertEqual(len(names), 4)

    # --- cambiar por otro: el presupuesto se ajusta al nuevo ---

    def test_replacement_updates_the_line_in_place_with_new_cost_and_price(self):
        search = self._scenario()
        self._change(search, replacement=self.line_b)
        line = self.order.order_line
        self.assertEqual(len(self.order.order_line), 1)
        self.assertEqual(line.restaurant_id, self.rest_b)
        self.assertEqual(line.restagrup_search_line_id, self.line_b)
        self.assertEqual(line.product_uom_qty, 42)  # una unidad por comensal
        self.assertAlmostEqual(line.restagrup_unit_cost, 800 / 42, places=2)
        self.assertAlmostEqual(line.price_unit, 960 / 42, places=2)  # 800 + 20 %, por persona
        self.assertAlmostEqual(line.price_subtotal, 960.0, delta=0.5)
        self.assertIn('Casa B', line.name)
        self.assertEqual(search.chosen_line_id, self.line_b)
        self.assertEqual(search.sale_order_id, self.order)

    def test_keep_client_price_leaves_the_price_and_changes_only_cost_and_margin(self):
        search = self._scenario()
        self._change(search, replacement=self.line_b, keep_client_price=True)
        line = self.order.order_line
        self.assertAlmostEqual(line.price_subtotal, 1200.0, delta=0.5)
        self.assertAlmostEqual(line.restagrup_unit_cost, 800 / 42, places=2)
        self.assertAlmostEqual(line.restagrup_margin_pct, 50.0, delta=0.1)

    def test_other_events_of_the_group_are_untouched(self):
        search = self._scenario()
        second = self._search(city='Sevilla', date='2026-11-16', pax=40)
        other = self._quote(second, self.rest_c, 500)
        other.action_toggle_chosen()
        second.action_create_sale_order()
        self.assertEqual(second.sale_order_id, self.order)
        self._change(search, replacement=self.line_b)
        self.assertEqual(self.order.order_line.mapped('restaurant_id'), self.rest_b | self.rest_c)
        self.assertEqual(second.chosen_line_id, other)

    def test_replacement_must_have_a_registered_quote_from_the_same_search(self):
        search = self._scenario()
        pending = self._quote(search, self.rest_c, 700, state='solicitado')
        with self.assertRaises(UserError):
            self._change(search, replacement=pending)
        foreign = self._quote(self._search(city='Sevilla'), self.rest_b, 600)
        with self.assertRaises(UserError):
            self._change(search, replacement=foreign)

    # --- presupuesto ya confirmado ---

    def test_confirmed_order_cancels_the_old_sheet_and_creates_the_new_one(self):
        search = self._scenario(confirm=True)
        self._change(search, replacement=self.line_b)
        sheets = self.order.restaurant_po_ids
        old = sheets.filtered(lambda po: po.partner_id == self.rest_a)
        new = sheets.filtered(lambda po: po.partner_id == self.rest_b)
        self.assertEqual(old.state, 'cancel')
        self.assertEqual(new.state, 'draft')
        self.assertEqual(self.order.restagrup_confirmation_summary, '0/1')
        self.assertIn('confirmado', ' '.join(self.order.message_ids.mapped('body')).lower())

    def test_confirmed_order_without_replacement_zeroes_the_line_instead_of_deleting_it(self):
        search = self._scenario(confirm=True)
        self._change(search)
        self.assertEqual(self.order.order_line.product_uom_qty, 0)
        self.assertIn('CANCELADO', self.order.order_line.name)
        self.assertEqual(self.order.restaurant_po_ids.state, 'cancel')

    # --- aviso al restaurante cancelado (la agencia no recibe nada) ---

    def test_notify_restaurant_sends_a_notice_and_the_agency_gets_nothing(self):
        search = self._scenario()
        mails_before = self.env['mail.mail'].search_count([('email_to', 'ilike', 'ag@example.com')])
        self._change(search, notify_restaurant=True, subject='Cancelación', body='<p>Hola {restaurante}</p>')
        notice = self.env['restagrup.restaurant.notice'].search([('restaurant_id', '=', self.rest_a)])
        self.assertEqual(notice.subject, 'Cancelación')
        self.assertIn('Casa A', notice.body)
        self.assertEqual(self.env['mail.mail'].search_count([('email_to', 'ilike', 'ag@example.com')]), mails_before)

    def test_notice_needs_subject_and_body_and_nothing_changes_if_it_fails(self):
        search = self._scenario()
        with self.assertRaises(UserError):
            self._change(search, notify_restaurant=True, subject='', body='')
        self.assertEqual(search.chosen_line_id, self.line_a)
        self.assertEqual(self.line_a.etiqueta, 'presupuesto_recibido')

    def test_cancellation_template_is_loaded(self):
        self.assertTrue(self.env.ref('restagrup_service_orders.notice_template_cancellation'))

    # --- validaciones y permisos ---

    def test_a_chosen_restaurant_and_a_reason_are_required(self):
        search = self._search()
        with self.assertRaises(UserError):
            self._change(search)
        search = self._scenario()
        with self.assertRaises(UserError):
            self._change(search, reason_id=False)

    def test_salesperson_without_purchase_rights_can_change_a_restaurant(self):
        search = self._scenario(confirm=True)
        user = self.env['res.users'].create({
            'name': 'Comercial cambio', 'login': 'comercial_cambio', 'email': 'cc@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('sales_team.group_sale_salesman').id])]})
        self.order.user_id = user
        self.lead.user_id = user
        wizard = self.env['restagrup.restaurant.change.wizard'].with_user(user).create({
            'search_id': search.id, 'reason_id': self.reason.id, 'replacement_line_id': self.line_b.id,
            'notify_restaurant': False})
        wizard.action_confirm()
        self.assertEqual(search.chosen_line_id, self.line_b)
