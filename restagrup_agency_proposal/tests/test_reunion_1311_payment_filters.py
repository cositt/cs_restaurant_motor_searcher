# -*- coding: utf-8 -*-
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import datetime as safe_datetime, safe_eval

from odoo.addons.restagrup_agency_proposal.models.payment_dates import restaurant_payment_due_date

SEARCH_VIEW = 'restagrup_agency_proposal.view_purchase_order_restaurant_payments_search'
ACTION = 'restagrup_agency_proposal.action_restaurant_payments'
# Reunión 23/11: + «Vencen en 1 semana»
FILTERS = {'restagrup_due_today': 0, 'restagrup_due_48h': 2, 'restagrup_due_72h': 3, 'restagrup_due_7d': 7}


@tagged('post_install', '-at_install')
class TestReunion1311PaymentFilters(TransactionCase):
    """Reunión 13/11 (P4): en «Pagos a restaurantes», botones «Vencen hoy» (con los vencidos), «Vencen en 48 h» y
    «Vencen en 72 h». Para filtrar, «Toca pagar el» tiene que estar guardado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('restagrup.send_mode', 'approval')
        params.search([('key', '=', 'restagrup.restaurant_payment_hours')]).unlink()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia filtros', 'email': 'filtros@example.com'})
        cls.today = fields.Date.context_today(cls.agency)

    def _sheet(self, days, terms='standard'):
        restaurant = self.env['res.partner'].create({
            'name': 'Casa filtros %s' % days, 'is_restaurant': True, 'email': 'filtros%s@example.com' % days,
            'restagrup_payment_terms': terms})
        product = self.env['product.template'].create({
            'name': 'Menú filtros', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0,
            'sale_ok': True, 'restaurant_id': restaurant.id}).product_variant_id
        lead = self.env['crm.lead'].create({'name': 'Grupo filtros', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_hour': 14.0,
                                   'service_date': self.today + timedelta(days=days)})]})
        order.action_confirm()
        return order.restaurant_po_ids

    def _filter_domains(self):
        arch = etree.fromstring(self.env.ref(SEARCH_VIEW).arch)
        context = {'context_today': lambda: self.today, 'relativedelta': relativedelta, 'datetime': safe_datetime}
        return {node.get('name'): safe_eval(node.get('domain'), context)
                for node in arch.iter('filter') if node.get('name') in FILTERS}

    # --- el campo se guarda y se recalcula ---

    def test_due_date_is_stored(self):
        self.assertTrue(self.env['purchase.order']._fields['restagrup_payment_due_date'].store)

    def test_due_date_can_be_searched(self):
        sheet = self._sheet(10)
        due = restaurant_payment_due_date(sheet.restagrup_service_date, 48)
        self.assertIn(sheet, self.env['purchase.order'].search([('restagrup_payment_due_date', '=', due)]))

    def test_due_date_follows_a_new_service_date(self):
        sheet = self._sheet(10)
        sale_line = sheet.order_line.restagrup_sale_line_id
        sale_line.service_date = self.today + timedelta(days=20)
        self.assertEqual(sheet.restagrup_payment_due_date,
                         restaurant_payment_due_date(self.today + timedelta(days=20), 48))

    def test_paying_the_deposit_moves_the_due_date_to_the_rule(self):
        sheet = self._sheet(10, terms='deposit')
        self.assertEqual(sheet.restagrup_payment_due_date, self.today)
        sheet.restagrup_deposit_paid = True
        self.assertEqual(sheet.restagrup_payment_due_date, restaurant_payment_due_date(sheet.restagrup_service_date, 48))

    # --- los tres botones ---

    def test_action_uses_the_payments_search_view(self):
        self.assertEqual(self.env.ref(ACTION).search_view_id, self.env.ref(SEARCH_VIEW))

    def test_three_due_filters_exist(self):
        self.assertEqual(set(self._filter_domains()), set(FILTERS))

    def test_each_filter_shows_what_is_due_up_to_its_day(self):
        for name, days in FILTERS.items():
            self.assertEqual(self._filter_domains()[name],
                             [('restagrup_payment_due_date', '<=', fields.Date.to_string(self.today + timedelta(days=days)))],
                             name)

    def test_due_today_includes_overdue_and_immediate_payments(self):
        immediate = self._sheet(10, terms='immediate')
        later = self._sheet(30)
        found = self.env['purchase.order'].search(self._filter_domains()['restagrup_due_today'])
        self.assertIn(immediate, found)
        self.assertNotIn(later, found)
