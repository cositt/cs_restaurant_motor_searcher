# -*- coding: utf-8 -*-
import re

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

CONFIRMATION = 'restagrup_agency_proposal.report_booking_confirmation'
RESTAURANT = 'restagrup_agency_proposal.report_restaurant_confirmation'
VOUCHER = 'restagrup_agency_proposal.report_booking_voucher'


def _text(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.decode()))


@tagged('post_install', '-at_install')
class TestBookingDocuments(TransactionCase):
    """Confirmación a la agencia, confirmación al restaurante y bono: la información va cambiando por el camino."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.company = cls.env.company
        cls.company.partner_id.bank_ids.unlink()  # solo la cuenta de este test
        cls.env['res.partner.bank'].create({
            'acc_number': 'ES6000494434232610005925', 'partner_id': cls.company.partner_id.id,
        })
        cls.client = cls.env['res.partner'].create({
            'name': 'Toma Viajes', 'email': 'ag@example.com', 'phone': '601 60 80 65'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Rústico Prueba', 'is_restaurant': True, 'email': 'rest@example.com',
            'street': 'Carretera de Medina km 2.5', 'city': 'Medina-Sidonia'})
        cls.menu_text = 'ENTRANTES COMPARTIDOS\nCARNE AL TORO\nPOSTRE DE LA CASA'
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'menu grupos 2026 fds', 'partner_id': cls.restaurant.id, 'cost_price': 30.0,
            'description': cls.menu_text})
        cls.product = cls.env['product.template'].create({
            'name': 'Menú grupos fds', 'type': 'service', 'standard_price': 30.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.client.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id, 'product_uom_qty': 50, 'restagrup_gratuities': 2,
                'service_date': '2026-12-20', 'service_hour': 13.5})],
        })
        cls.line = cls.order.order_line

    def _html(self, report, records):
        return self.env['ir.actions.report']._render_qweb_html(report, records.ids)[0]

    def _purchase(self):
        self.order.action_confirm()
        return self.order.restaurant_po_ids[:1]

    # --- datos del servicio ---

    def test_service_info_counts_total_diners_with_gratuities(self):
        info = self.line._restagrup_service_info()
        self.assertEqual((info['paying'], info['gratuities'], info['pax_total']), (50, 2, 52))
        self.assertEqual(info['hour'], '13:30')
        self.assertEqual(info['date'], '20/12/2026')

    def test_service_info_menu_text_comes_from_the_chosen_menu(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo doc'})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Medina', 'min_capacity': 52})
        search_line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': 1500.0,
            'menu_id': self.menu.id})
        self.line.restagrup_search_line_id = search_line
        self.assertIn('CARNE AL TORO', self.line._restagrup_service_info()['menu_text'])

    # --- confirmación a la agencia ---

    def test_agency_confirmation_shows_gratuities_total_and_bank(self):
        text = _text(self._html(CONFIRMATION, self.order))
        self.assertIn('CONFIRMACIÓN DE RESERVA', text)
        self.assertIn('Toma Viajes', text)
        self.assertIn('Mesón Rústico Prueba', text)
        self.assertIn('Medina-Sidonia', text)
        self.assertIn('50 + 2 gratuidades', text)
        self.assertIn('IVA INCLUIDO', text)
        self.assertIn('ES60 0049 4434 2326 1000 5925', text)
        self.assertIn('48 horas laborables', text)

    def test_agency_confirmation_never_shows_restaurant_cost_or_margin(self):
        text = _text(self._html(CONFIRMATION, self.order))
        self.assertNotRegex(text, r'(?<!\d)30[.,]00')
        self.assertNotRegex(text, r'1[.,\s\xa0]?500[.,]00')

    def test_observations_reach_agency_and_restaurant_documents_only(self):
        self.order.restagrup_observations = 'Guía: Marta 600111222. Un celíaco.'
        self.assertIn('Un celíaco', _text(self._html(CONFIRMATION, self.order)))
        self.assertIn('Un celíaco', _text(self._html(RESTAURANT, self._purchase())))

    # --- confirmación al restaurante ---

    def test_restaurant_confirmation_has_cost_price_and_no_client_price(self):
        text = _text(self._html(RESTAURANT, self._purchase()))
        self.assertIn('CONFIRMACIÓN DE RESERVA RESTAURANTE', text)
        self.assertIn('50 + 2 gratuidades', text)
        self.assertRegex(text, r'30[.,]00')
        self.assertRegex(text, r'1[.,\s\xa0]?500[.,]00')
        self.assertNotRegex(text, r'(?<!\d)36[.,]00')
        self.assertNotRegex(text, r'1[.,\s\xa0]?800[.,]00')

    # --- pago y bono ---

    def test_voucher_is_blocked_until_the_order_is_paid(self):
        with self.assertRaises(UserError):
            self.order.action_print_voucher()

    def test_marking_paid_records_the_date_and_unlocks_the_voucher(self):
        self.order.action_mark_paid()
        self.assertTrue(self.order.restagrup_paid)
        self.assertTrue(self.order.restagrup_paid_date)
        action = self.order.action_print_voucher()
        # Sin el diseño de documentos configurado, Odoo envuelve el informe en su asistente de diseño.
        report_action = action.get('context', {}).get('report_action', action)
        self.assertEqual(report_action['report_name'], VOUCHER)

    def test_unmarking_paid_blocks_the_voucher_again(self):
        self.order.action_mark_paid()
        self.order.action_unmark_paid()
        self.assertFalse(self.order.restagrup_paid)
        with self.assertRaises(UserError):
            self.order.action_print_voucher()

    def test_voucher_has_the_paid_stamp_and_no_prices(self):
        self.order.action_mark_paid()
        text = _text(self._html(VOUCHER, self.order))
        self.assertIn('BONO DE SERVICIO', text)
        self.assertIn('PAGADO', text)
        self.assertIn('Total comensales: 52', text)
        self.assertNotRegex(text, r'(?<!\d)36[.,]00')
        self.assertNotRegex(text, r'1[.,\s\xa0]?800[.,]00')
        self.assertNotRegex(text, r'(?<!\d)30[.,]00')
