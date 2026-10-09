# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleOrderFollowup(TransactionCase):
    """D: resumen de confirmaciones por restaurante. E: proforma actualizada a la agencia."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))  # sin puntos de revisión
        cls.agency = cls.env['res.partner'].create({
            'name': 'Agencia Test', 'email': 'agencia@example.com',
        })
        cls.product = cls.env['product.product'].create({'name': 'Menú grupo', 'type': 'service'})
        cls.restaurants = cls.env['res.partner'].create([
            {'name': 'Rest A', 'is_restaurant': True, 'email': 'a@example.com'},
            {'name': 'Rest B', 'is_restaurant': True, 'email': 'b@example.com'},
            {'name': 'Rest C', 'is_restaurant': True, 'email': 'c@example.com'},
        ])

    def _confirmed_order(self, restaurants=None, agency=None):
        restaurants = restaurants or self.restaurants
        order = self.env['sale.order'].create({
            'partner_id': (agency or self.agency).id,
            'order_line': [(0, 0, {
                'product_id': self.product.id, 'product_uom_qty': 10, 'price_unit': 20,
                'restaurant_id': r.id,
            }) for r in restaurants],
        })
        order.action_confirm()
        return order

    def _agency_mails(self, order):
        return self.env['mail.mail'].search([
            ('model', '=', 'sale.order'), ('res_id', '=', order.id),
        ])

    # --- D: resumen confirmados / pendientes ---

    def test_counts_without_restaurant_sheets_are_zero(self):
        order = self.env['sale.order'].create({'partner_id': self.agency.id})
        self.assertEqual(order.restagrup_confirmed_count, 0)
        self.assertEqual(order.restagrup_pending_count, 0)
        self.assertFalse(order.restagrup_confirmation_summary)

    def test_counts_all_pending_after_confirm(self):
        order = self._confirmed_order()
        self.assertEqual(order.restagrup_confirmed_count, 0)
        self.assertEqual(order.restagrup_pending_count, 3)

    def test_counts_accepted_sheet_as_confirmed(self):
        order = self._confirmed_order()
        order.restaurant_po_ids[0].restagrup_response_state = 'accepted'
        self.assertEqual(order.restagrup_confirmed_count, 1)
        self.assertEqual(order.restagrup_pending_count, 2)

    def test_rejected_or_unclear_is_still_pending(self):
        order = self._confirmed_order()
        order.restaurant_po_ids[0].restagrup_response_state = 'rejected'
        order.restaurant_po_ids[1].restagrup_response_state = 'unclear'
        self.assertEqual(order.restagrup_confirmed_count, 0)
        self.assertEqual(order.restagrup_pending_count, 3)

    def test_cancelled_sheet_is_excluded_from_both_counts(self):
        order = self._confirmed_order()
        order.restaurant_po_ids[0].state = 'cancel'
        order.restaurant_po_ids[1].restagrup_response_state = 'accepted'
        self.assertEqual(order.restagrup_confirmed_count, 1)
        self.assertEqual(order.restagrup_pending_count, 1)

    def test_summary_text_shows_confirmed_over_total(self):
        order = self._confirmed_order()
        order.restaurant_po_ids[0].restagrup_response_state = 'accepted'
        self.assertEqual(order.restagrup_confirmation_summary, '1/3')

    # --- E: proforma actualizada a la agencia ---

    def _change_quantity_and_resend(self, order):
        order.order_line[0].product_uom_qty = 15
        self.assertTrue(order.restaurant_changes_pending)
        order.action_resend_restaurant_orders()

    def test_resend_also_emails_updated_order_to_agency(self):
        order = self._confirmed_order()
        order.action_send_restaurant_orders()
        before = self._agency_mails(order)
        self._change_quantity_and_resend(order)
        new_mails = self._agency_mails(order) - before
        self.assertEqual(len(new_mails), 1)
        self.assertIn('agencia@example.com', new_mails.email_to or new_mails.recipient_ids.email)

    def test_resend_without_changes_does_not_email_agency(self):
        order = self._confirmed_order()
        order.action_send_restaurant_orders()
        before = self._agency_mails(order)
        order.action_resend_restaurant_orders()
        self.assertEqual(self._agency_mails(order), before)

    def test_resend_agency_without_email_leaves_note_and_does_not_fail(self):
        no_email_agency = self.env['res.partner'].create({'name': 'Agencia sin email'})
        order = self._confirmed_order(agency=no_email_agency)
        order.action_send_restaurant_orders()
        self._change_quantity_and_resend(order)
        self.assertFalse(self._agency_mails(order))
        notes = order.message_ids.filtered(lambda m: 'agencia' in (m.body or '').lower())
        self.assertTrue(notes)
