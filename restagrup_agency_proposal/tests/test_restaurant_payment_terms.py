# -*- coding: utf-8 -*-
"""Pago al restaurante según la respuesta de Conchita (2026-11-09):
- Norma: 48 h antes del servicio; los viernes se pagan también los grupos del lunes y del martes.
- Algunos restaurantes piden pago inmediato o una señal del 50 %: se apunta en su ficha.
- Con señal, el pago final es el total menos la señal ya pagada (antes se pagaba a veces el 100 %)."""
import re
from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.restagrup_agency_proposal.models.payment_dates import restaurant_payment_due_date

CONFIRMATION = 'restagrup_agency_proposal.report_restaurant_confirmation'


def _text(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.decode()))


@tagged('post_install', '-at_install')
class TestRestaurantPaymentTerms(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('restagrup.send_mode', 'approval')
        for key in ('payment_request_days', 'restaurant_payment_hours'):
            params.search([('key', '=', 'restagrup.%s' % key)]).unlink()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia condiciones', 'email': 'cond@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa condiciones', 'is_restaurant': True, 'email': 'casa@example.com'})
        cls.env['res.partner.bank'].create({'partner_id': cls.restaurant.id, 'acc_number': 'ES7921000813610123456789'})

    def _sheet(self, days):
        product = self.env['product.template'].create({
            'name': 'Menú condiciones', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0,
            'sale_ok': True, 'restaurant_id': self.restaurant.id}).product_variant_id
        lead = self.env['crm.lead'].create({'name': 'Grupo condiciones', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_hour': 14.0,
                                   'service_date': fields.Date.context_today(lead) + timedelta(days=days)})]})
        order.action_confirm()
        return order.restaurant_po_ids

    def _cron(self):
        self.env['purchase.order']._cron_restaurant_payments()

    # --- regla del viernes ---

    def test_wednesday_service_is_paid_on_monday(self):
        self.assertEqual(restaurant_payment_due_date(date(2026, 11, 18), 48), date(2026, 11, 16))

    def test_monday_and_tuesday_services_are_paid_on_friday(self):
        self.assertEqual(restaurant_payment_due_date(date(2026, 11, 16), 48), date(2026, 11, 13))
        self.assertEqual(restaurant_payment_due_date(date(2026, 11, 17), 48), date(2026, 11, 13))

    def test_weekend_services_keep_the_48_hours(self):
        self.assertEqual(restaurant_payment_due_date(date(2026, 11, 14), 48), date(2026, 11, 12))  # sábado → jueves
        self.assertEqual(restaurant_payment_due_date(date(2026, 11, 15), 48), date(2026, 11, 13))  # domingo → viernes

    def test_without_service_date_there_is_no_due_date(self):
        self.assertFalse(restaurant_payment_due_date(False, 48))

    def test_sheet_due_date_uses_the_friday_rule(self):
        sheet = self._sheet(10)
        self.assertEqual(sheet.restagrup_payment_due_date,
                         restaurant_payment_due_date(sheet.restagrup_service_date, 48))

    def test_sale_order_payment_date_uses_the_friday_rule(self):
        sheet = self._sheet(10)
        order = sheet.restagrup_sale_order_id
        self.assertEqual(order.restagrup_restaurant_payment_date,
                         restaurant_payment_due_date(order.restagrup_first_service_date, 48))

    # --- condiciones del restaurante ---

    def test_restaurants_pay_48_hours_before_by_default(self):
        self.assertEqual(self.restaurant.restagrup_payment_terms, 'standard')
        self.assertEqual(self.restaurant.restagrup_deposit_percent, 50.0)

    def test_immediate_payment_is_due_as_soon_as_the_sheet_exists(self):
        self.restaurant.restagrup_payment_terms = 'immediate'
        sheet = self._sheet(30)
        self.assertEqual(sheet.restagrup_payment_due_date, fields.Date.context_today(sheet))
        self._cron()
        self.assertTrue(sheet.restagrup_payment_due)

    def test_far_standard_sheet_is_not_due(self):
        sheet = self._sheet(30)
        self._cron()
        self.assertFalse(sheet.restagrup_payment_due)

    # --- señal ---

    def test_deposit_is_due_now_and_the_rest_48_hours_before(self):
        self.restaurant.restagrup_payment_terms = 'deposit'
        sheet = self._sheet(30)
        self.assertAlmostEqual(sheet.restagrup_deposit_amount, sheet.amount_total / 2)
        self.assertEqual(sheet.restagrup_payment_due_date, fields.Date.context_today(sheet))
        self._cron()
        self.assertTrue(sheet.restagrup_payment_due)
        sheet.action_mark_deposit_paid()
        self.assertTrue(sheet.restagrup_deposit_paid)
        self.assertFalse(sheet.restagrup_payment_due)
        self.assertEqual(sheet.restagrup_payment_due_date,
                         restaurant_payment_due_date(sheet.restagrup_service_date, 48))

    def test_after_the_deposit_only_the_rest_is_left_to_pay(self):
        self.restaurant.write({'restagrup_payment_terms': 'deposit', 'restagrup_deposit_percent': 30.0})
        sheet = self._sheet(30)
        self.assertAlmostEqual(sheet.restagrup_amount_to_pay, sheet.amount_total)
        sheet.action_mark_deposit_paid()
        self.assertAlmostEqual(sheet.restagrup_amount_to_pay, sheet.amount_total * 0.7)
        self.assertIn('señal', sheet.message_ids[:1].body.lower())

    def test_final_payment_note_says_the_deposit_was_discounted(self):
        self.restaurant.restagrup_payment_terms = 'deposit'
        sheet = self._sheet(30)
        sheet.action_mark_deposit_paid()
        sheet.action_mark_restaurant_paid()
        self.assertTrue(any('descontada' in (m.body or '') for m in sheet.message_ids))
        self.assertAlmostEqual(sheet.restagrup_amount_to_pay, 0.0)

    def test_deposit_button_only_for_deposit_restaurants(self):
        arch = self.env.ref('restagrup_agency_proposal.view_purchase_order_form_close_checklist').get_combined_arch()
        self.assertIn('action_mark_deposit_paid', arch)
        self.assertIn('restagrup_amount_to_pay', arch)
        partner_arch = self.env['res.partner'].get_view(
            self.env.ref('restagrup_restaurants.view_partner_form_restaurant').id, 'form')['arch']
        self.assertIn('restagrup_payment_terms', partner_arch)

    # --- texto de la confirmación al restaurante ---

    def test_confirmation_text_follows_the_terms(self):
        sheet = self._sheet(30)
        self.assertIn('48 h', sheet.restagrup_restaurant_bank_text())
        self.restaurant.restagrup_payment_terms = 'immediate'
        self.assertIn('a la confirmación', sheet.restagrup_restaurant_bank_text())
        self.restaurant.restagrup_payment_terms = 'deposit'
        text = sheet.restagrup_restaurant_bank_text()
        self.assertIn('señal del 50 %', text)
        self.assertIn('48 h', text)
        self.assertIn('señal', _text(self.env['ir.actions.report']._render_qweb_html(CONFIRMATION, sheet.ids)[0]))
