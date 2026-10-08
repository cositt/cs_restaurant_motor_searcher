# -*- coding: utf-8 -*-
import re
from datetime import date

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

SETTINGS = 'restagrup.payment.settings'


def _text(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.decode()))


@tagged('post_install', '-at_install')
class TestPaymentSettings(TransactionCase):
    """Plazos y textos de pago configurables por RestaGrup: ellos los llevan, el sistema solo los calcula y muestra."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env['ir.config_parameter'].sudo()
        for key in ('payment_request_days', 'payment_alert_hours', 'restaurant_payment_hours', 'final_pax_hours',
                    'invoice_days', 'payment_request_text', 'payment_urgent_text'):
            cls.params.search([('key', '=', 'restagrup.%s' % key)]).unlink()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia plazos', 'email': 'ag@example.com'})
        cls.restaurant = cls.env['res.partner'].create({'name': 'Casa plazos', 'is_restaurant': True})
        product = cls.env['product.template'].create({
            'name': 'Menú plazos', 'type': 'service', 'standard_price': 20.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.agency.id,
            'order_line': [
                (0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_date': '2026-12-20', 'service_hour': 13.0}),
                (0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_date': '2026-12-22', 'service_hour': 13.0}),
            ]})

    def _set(self, key, value):
        self.params.set_param('restagrup.%s' % key, value)
        self.env.invalidate_all()  # los plazos se calculan al leer; en un test la caché sobrevive entre lecturas

    # --- valores ---

    def test_defaults_follow_the_clients_manual(self):
        settings = self.env[SETTINGS]
        self.assertEqual(
            [settings.value(k) for k in ('payment_request_days', 'payment_alert_hours', 'restaurant_payment_hours',
                                         'final_pax_hours', 'invoice_days')],
            [7, 72, 48, 48, 7])

    def test_values_can_be_changed(self):
        self._set('payment_request_days', '10')
        self.assertEqual(self.env[SETTINGS].value('payment_request_days'), 10)

    def test_a_wrong_value_falls_back_to_the_default(self):
        self._set('payment_alert_hours', 'abc')
        self.assertEqual(self.env[SETTINGS].value('payment_alert_hours'), 72)

    def test_saving_the_settings_screen_stores_the_values(self):
        self.env['res.config.settings'].create({
            'restagrup_payment_request_days': 9, 'restagrup_final_pax_hours': 24,
            'restagrup_payment_request_text': 'Hola {agencia}, el pago, por favor.',
        }).execute()
        self.assertEqual(self.env[SETTINGS].value('payment_request_days'), 9)
        self.assertEqual(self.env[SETTINGS].value('final_pax_hours'), 24)
        self.assertEqual(self.env[SETTINGS].text('payment_request_text'), 'Hola {agencia}, el pago, por favor.')

    # --- plazos del pedido ---

    def test_deadlines_are_counted_from_the_first_and_last_service(self):
        order = self.order
        self.assertEqual(order.restagrup_first_service_date, date(2026, 12, 20))
        self.assertEqual(order.restagrup_last_service_date, date(2026, 12, 22))
        self.assertEqual(order.restagrup_payment_request_date, date(2026, 12, 13))   # 7 días antes
        self.assertEqual(order.restagrup_payment_alert_date, date(2026, 12, 17))     # 72 h antes
        self.assertEqual(order.restagrup_restaurant_payment_date, date(2026, 12, 18))  # 48 h antes
        self.assertEqual(order.restagrup_invoice_deadline, date(2026, 12, 29))       # 7 días tras el último

    def test_changing_the_settings_moves_the_deadlines(self):
        self._set('payment_request_days', '14')
        self._set('invoice_days', '3')
        self.assertEqual(self.order.restagrup_payment_request_date, date(2026, 12, 6))
        self.assertEqual(self.order.restagrup_invoice_deadline, date(2026, 12, 25))

    def test_without_service_dates_there_are_no_deadlines(self):
        order = self.env['sale.order'].create({'partner_id': self.agency.id})
        self.assertFalse(order.restagrup_payment_request_date)
        self.assertFalse(order.restagrup_invoice_deadline)

    # --- textos ---

    def test_payment_request_text_names_the_agency(self):
        self.assertIn('Agencia plazos', self.order.restagrup_payment_request_text)
        self.assertNotIn('{agencia}', self.order.restagrup_payment_request_text)

    def test_custom_texts_are_used(self):
        self._set('payment_request_text', 'Pago de {agencia}, gracias.')
        self.assertEqual(self.order.restagrup_payment_request_text, 'Pago de Agencia plazos, gracias.')
        self._set('payment_urgent_text', 'URGENTE {agencia}')
        self.assertEqual(self.order.restagrup_payment_urgent_text, 'URGENTE Agencia plazos')

    # --- los documentos usan los plazos ---

    def test_confirmation_note_uses_the_configured_hours(self):
        self._set('final_pax_hours', '24')
        html = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_agency_proposal.report_booking_confirmation', self.order.ids)[0]
        self.assertIn('24 horas laborables', _text(html))
        self.assertNotIn('48 horas laborables', _text(html))

    # --- lista de pagos pendientes ---

    def test_pending_payments_list_shows_confirmed_unpaid_orders(self):
        self.order.action_confirm()
        action = self.env.ref('restagrup_agency_proposal.action_pending_payments')
        domain = safe_eval(action.domain)
        self.assertIn(self.order, self.env['sale.order'].search(domain))
        self.order.action_mark_paid()
        self.assertNotIn(self.order, self.env['sale.order'].search(domain))
