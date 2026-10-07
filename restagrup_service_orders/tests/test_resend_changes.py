# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo.tests.common import TransactionCase, tagged

SERVICE_DATE = date(2026, 12, 15)


@tagged('post_install', '-at_install')
class TestResendChanges(TransactionCase):
    """A7: «Reenviar cambios» dice qué cambió, detecta fecha, hora y menú, y pide confirmación si el cambio
    es significativo (fecha/hora, o comensales por encima del umbral)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.change_confirm_pct')]).unlink()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia A7', 'email': 'agencia-a7@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante A7', 'is_restaurant': True, 'email': 'rest-a7@example.com'})
        Product = cls.env['product.product']
        cls.menu_a = Product.create({
            'name': 'Menú A7 clásico', 'type': 'service', 'standard_price': 20, 'restaurant_id': cls.restaurant.id})
        cls.menu_b = Product.create({
            'name': 'Menú A7 premium', 'type': 'service', 'standard_price': 30, 'restaurant_id': cls.restaurant.id})

    def _order(self, pax=10, hour=13.5):
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id,
            'order_line': [(0, 0, {
                'product_id': self.menu_a.id, 'product_uom_qty': pax, 'price_unit': 25,
                'restaurant_id': self.restaurant.id, 'service_date': SERVICE_DATE, 'service_hour': hour,
            })],
        })
        order.action_confirm()
        order.action_send_restaurant_orders()
        self.po = order.sudo().restaurant_po_ids
        self.po.restagrup_response_state = 'accepted'
        return order

    def _resend(self, order, **line_vals):
        order.order_line.write(line_vals)
        order.action_resend_restaurant_orders()

    def _mail_to(self, record):
        return self.env['mail.mail'].search([('model', '=', record._name), ('res_id', '=', record.id)],
                                            order='id desc', limit=1)

    # --- la hora viaja a la hoja de servicio ---

    def test_sheet_line_carries_service_date_and_hour(self):
        self._order(hour=13.5)
        self.assertEqual(self.po.order_line.date_planned, datetime(2026, 12, 15, 13, 30))

    def test_line_without_hour_plans_midnight(self):
        self._order(hour=0.0)
        self.assertEqual(self.po.order_line.date_planned, datetime(2026, 12, 15, 0, 0))

    # --- detección ---

    def test_nothing_changed_nothing_pending(self):
        self._order()
        self.assertFalse(self.po.restagrup_needs_resend)

    def test_hour_date_and_menu_changes_are_detected(self):
        order = self._order()
        order.order_line.service_hour = 14.0
        self.assertTrue(self.po.restagrup_needs_resend)
        order.order_line.service_hour = 13.5
        self.assertFalse(self.po.restagrup_needs_resend)
        order.order_line.service_date = date(2026, 12, 16)
        self.assertTrue(self.po.restagrup_needs_resend)
        order.order_line.service_date = SERVICE_DATE
        order.order_line.product_id = self.menu_b
        self.assertTrue(self.po.restagrup_needs_resend)

    # --- resumen en el correo ---

    def test_email_to_restaurant_lists_the_changes(self):
        order = self._order()
        self._resend(order, product_uom_qty=11, service_hour=14.0)
        body = self._mail_to(self.po).body_html
        self.assertIn('Comensales 10 → 11', body)
        self.assertIn('Hora 13:30 → 14:00', body)

    def test_email_to_agency_lists_changes_by_restaurant(self):
        order = self._order()
        self._resend(order, product_uom_qty=11)
        body = self._mail_to(order).body_html
        self.assertIn('Restaurante A7', body)
        self.assertIn('Comensales 10 → 11', body)

    def test_menu_change_is_listed_updates_cost_and_only_informs(self):
        order = self._order()
        self._resend(order, product_id=self.menu_b.id)
        self.assertIn('Menú A7 clásico → Menú A7 premium', self._mail_to(self.po).body_html)
        self.assertEqual(self.po.order_line.product_id, self.menu_b)
        self.assertEqual(self.po.order_line.price_unit, 30)
        self.assertEqual(self.po.restagrup_response_state, 'accepted')

    def test_resend_syncs_sheet_and_clears_pending(self):
        order = self._order()
        self._resend(order, service_hour=14.0, product_uom_qty=11)
        self.assertEqual(self.po.order_line.date_planned, datetime(2026, 12, 15, 14, 0))
        self.assertEqual(self.po.order_line.product_qty, 11)
        self.assertFalse(self.po.restagrup_needs_resend)

    # --- cuándo pide confirmación ---

    def test_small_pax_change_only_informs(self):
        order = self._order(pax=10)
        self._resend(order, product_uom_qty=11)  # 10 %
        self.assertEqual(self.po.restagrup_response_state, 'accepted')
        self.assertEqual(order.restagrup_confirmed_count, 1)
        self.assertNotIn('Necesitamos que confirméis', self._mail_to(self.po).body_html)

    def test_big_pax_change_resets_to_pending_and_asks_to_confirm(self):
        order = self._order(pax=10)
        self._resend(order, product_uom_qty=15)  # 50 %
        self.assertFalse(self.po.restagrup_response_state)
        self.assertEqual(order.restagrup_confirmed_count, 0)
        self.assertEqual(order.restagrup_pending_count, 1)
        self.assertIn('Necesitamos que confirméis', self._mail_to(self.po).body_html)

    def test_hour_or_date_change_always_asks_to_confirm(self):
        order = self._order()
        self._resend(order, service_hour=14.0)
        self.assertFalse(self.po.restagrup_response_state)
        self.po.restagrup_response_state = 'accepted'
        self._resend(order, service_date=date(2026, 12, 20))
        self.assertFalse(self.po.restagrup_response_state)

    def test_notes_only_change_informs(self):
        order = self._order()
        self._resend(order, name='Menú con 2 celíacos')
        self.assertEqual(self.po.restagrup_response_state, 'accepted')
        self.assertIn('Observaciones', self._mail_to(self.po).body_html)

    def test_threshold_is_configurable(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.change_confirm_pct', '60')
        order = self._order(pax=10)
        self._resend(order, product_uom_qty=15)  # 50 % < 60 %
        self.assertEqual(self.po.restagrup_response_state, 'accepted')

    def test_threshold_boundary_is_not_significant(self):
        order = self._order(pax=10)
        self._resend(order, product_uom_qty=12)  # justo 20 %: «por encima» es estricto
        self.assertEqual(self.po.restagrup_response_state, 'accepted')

    def test_change_is_logged_in_sheet_chatter(self):
        order = self._order()
        self._resend(order, product_uom_qty=15)
        notes = ' '.join(self.po.message_ids.mapped('body'))
        self.assertIn('Comensales 10 → 15', notes)
