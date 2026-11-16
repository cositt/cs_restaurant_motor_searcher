# -*- coding: utf-8 -*-
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import datetime as safe_datetime, safe_eval

PREFIX = 'restagrup_agency_proposal.'
FILTERS = {
    'filter_orders_service_two_weeks': 'sale.order',
    'filter_orders_unpaid_by_agency': 'sale.order',
    'filter_orders_by_agency': 'sale.order',
    'filter_sheets_by_restaurant': 'purchase.order',
}


@tagged('post_install', '-at_install')
class TestReunion1311SavedFilters(TransactionCase):
    """Reunión 13/11 (P5): búsquedas ya hechas y visibles para todos en Pedidos y Hojas de restaurante."""

    def _eval(self, text):
        today = fields.Date.context_today(self.env.user)
        return safe_eval(text, {'context_today': lambda: today, 'relativedelta': relativedelta,
                                'datetime': safe_datetime, 'uid': self.env.uid})

    def test_filters_exist_for_everyone(self):
        for xmlid, model in FILTERS.items():
            saved = self.env.ref(PREFIX + xmlid)
            self.assertEqual(saved.model_id, model, xmlid)
            self.assertFalse(saved.user_ids, xmlid)  # compartido con todos
            self.assertFalse(saved.action_id, xmlid)  # sale en cualquier lista de ese modelo

    def test_domains_and_groupings_evaluate(self):
        for xmlid, model in FILTERS.items():
            saved = self.env.ref(PREFIX + xmlid)
            self.env[model].search(self._eval(saved.domain))
            self.assertIsInstance(self._eval(saved.context), dict)

    def test_service_window_is_today_to_two_weeks(self):
        domain = self._eval(self.env.ref(PREFIX + 'filter_orders_service_two_weeks').domain)
        today = fields.Date.context_today(self.env.user)
        self.assertIn(('restagrup_service_date', '>=', fields.Date.to_string(today)), domain)
        self.assertIn(('restagrup_service_date', '<=', fields.Date.to_string(today + timedelta(days=14))), domain)

    def test_unpaid_filter_shows_confirmed_orders_not_paid(self):
        domain = self._eval(self.env.ref(PREFIX + 'filter_orders_unpaid_by_agency').domain)
        self.assertIn(('state', '=', 'sale'), domain)
        self.assertIn(('restagrup_paid', '=', False), domain)

    def test_groupings(self):
        self.assertEqual(self._eval(self.env.ref(PREFIX + 'filter_orders_by_agency').context)['group_by'],
                         ['partner_id'])
        self.assertEqual(self._eval(self.env.ref(PREFIX + 'filter_sheets_by_restaurant').context)['group_by'],
                         ['partner_id', 'restagrup_service_date:day'])
