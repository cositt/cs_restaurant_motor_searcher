# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged

WIZARD = 'restagrup.firewall.wizard'


@tagged('post_install', '-at_install')
class TestFirewallDocuments(TransactionCase):
    """Cortafuegos de los documentos: la confirmación a la agencia exige la del restaurante por escrito."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.partner_id.bank_ids.unlink()
        cls.client = cls.env['res.partner'].create({'name': 'Agencia doc', 'email': 'ag@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa doc', 'is_restaurant': True, 'email': 'rest@example.com'})
        product = cls.env['product.template'].create({
            'name': 'Menú doc', 'type': 'service', 'standard_price': 30.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.client.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 40,
                                   'service_date': '2026-12-20', 'service_hour': 13.5})]})
        cls.order.action_confirm()
        cls.po = cls.order.restaurant_po_ids[:1]

    def _codes(self, record, trigger):
        return {i['check'].code for i in record._restagrup_firewall_issues(trigger)}

    def test_agency_confirmation_warns_about_everything_missing(self):
        self.assertEqual(self._codes(self.order, 'confirm_agency'),
                         {'restaurant_confirmed', 'restaurant_bank', 'company_bank'})

    def test_agency_confirmation_returns_a_warning_wizard_first(self):
        action = self.order.action_confirmation_agency()
        self.assertEqual(action['res_model'], WIZARD)
        wizard = self.env[WIZARD].browse(action['res_id'])
        self.assertIn('Casa doc', wizard.message)

    def test_continuing_returns_the_report(self):
        wizard = self.env[WIZARD].browse(self.order.action_confirmation_agency()['res_id'])
        result = wizard.action_continue()
        inner = result.get('context', {}).get('report_action', result)
        self.assertEqual(inner['report_name'], 'restagrup_agency_proposal.report_booking_confirmation')

    def test_clean_order_prints_without_asking(self):
        self.po.restagrup_response_state = 'accepted'
        self.restaurant.write({'bank_ids': [(0, 0, {'acc_number': 'ES6000494434232610005925'})]})
        self.env['res.partner.bank'].create({'acc_number': 'ES9121000418450200051332', 'partner_id': self.company.partner_id.id})
        self.assertEqual(self._codes(self.order, 'confirm_agency'), set())
        result = self.order.action_confirmation_agency()
        inner = result.get('context', {}).get('report_action', result)
        self.assertEqual(inner.get('report_name'), 'restagrup_agency_proposal.report_booking_confirmation')

    def test_restaurant_iban_on_its_sheet_counts_as_bank_account(self):
        self.restaurant.restaurant_iban = 'ES6000494434232610005925'
        self.assertNotIn('restaurant_bank', self._codes(self.order, 'confirm_agency'))
        self.restaurant.restaurant_iban = False
        self.assertIn('restaurant_bank', self._codes(self.order, 'confirm_agency'))

    def test_restaurant_not_accepted_when_it_answered_something_else(self):
        self.po.restagrup_response_state = 'needs_info'
        self.assertIn('restaurant_confirmed', self._codes(self.order, 'confirm_agency'))

    def test_restaurant_confirmation_warns_without_date_or_email(self):
        self.restaurant.email = False
        self.order.order_line.service_date = False
        self.assertEqual(self._codes(self.po, 'confirm_restaurant'), {'service_datetime', 'restaurant_email'})

    def test_restaurant_confirmation_is_clean_with_date_hour_and_email(self):
        self.assertEqual(self._codes(self.po, 'confirm_restaurant'), set())
        result = self.po.action_confirmation_restaurant()
        inner = result.get('context', {}).get('report_action', result)
        self.assertEqual(inner.get('report_name'), 'restagrup_agency_proposal.report_restaurant_confirmation')


@tagged('post_install', '-at_install')
class TestFirewallClose(TransactionCase):
    """Cerrar el expediente: cobro recibido y servicio terminado."""

    def _lead_with_confirmed_order(self, event_date):
        agency = self.env['res.partner'].create({'name': 'Agencia cierre', 'email': 'ag@example.com'})
        restaurant = self.env['res.partner'].create({'name': 'Casa cierre', 'is_restaurant': True})
        lead = self.env['crm.lead'].create({'name': 'Grupo cierre', 'partner_id': agency.id})
        self.env['restagrup.lead.event'].create({'lead_id': lead.id, 'city': 'Sevilla', 'event_date': event_date, 'pax': 30})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 30})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 900.0})
        line.action_toggle_chosen()
        search.action_create_sale_order()
        search.sale_order_id.action_confirm()
        return lead, search.sale_order_id

    def _codes(self, lead):
        return {i['check'].code for i in lead._restagrup_firewall_issues('close_file')}

    def test_warns_when_unpaid_and_service_not_done(self):
        lead, _order = self._lead_with_confirmed_order(date.today() + timedelta(days=10))
        self.assertEqual(self._codes(lead), {'paid', 'service_done'})

    def test_clean_when_paid_and_service_done(self):
        lead, order = self._lead_with_confirmed_order(date.today() - timedelta(days=2))
        order.action_mark_paid()
        self.assertEqual(self._codes(lead), set())

    def test_warns_when_there_is_no_confirmed_order(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo sin pedido'})
        self.assertIn('paid', self._codes(lead))
