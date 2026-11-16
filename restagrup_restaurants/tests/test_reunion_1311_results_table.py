# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion1311ResultsTable(TransactionCase):
    """Reunión 13/11 (P2): los resultados del buscador se ven en tarjetas o en tabla, y se pueden ordenar por el
    precio real por persona (no por el €/€€ de Google)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        lead = cls.env['crm.lead'].create({'name': 'Grupo tabla'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 30})

    def _line(self, name, price=0.0, google_level=False):
        restaurant = self.env['res.partner'].create({'name': name, 'is_restaurant': True})
        vals = {'search_id': self.search.id, 'source': 'partner', 'name': name, 'partner_id': restaurant.id,
                'etiqueta': 'interesado', 'price_level': google_level}
        if price:
            vals.update(etiqueta='presupuesto_recibido', quote_price_pp=price,
                        quote_received_date='2026-11-16 10:00:00')
        return self.env[LINE].create(vals)

    def test_cards_are_the_default_view(self):
        self.assertEqual(self.search.results_view, 'cards')

    def test_table_shows_the_same_results(self):
        lines = self._line('Uno', 10) | self._line('Dos')
        self.assertEqual(self.search.line_table_ids, lines)

    def test_sort_by_real_price_puts_unknown_prices_last(self):
        cheap_google_expensive = self._line('Caro', 30, google_level='1')
        unknown = self._line('Sin precio', google_level='1')
        cheap = self._line('Barato', 12, google_level='3')
        self.search.sort_by = 'agency_price_asc'
        self.search.action_apply_sort()
        self.assertEqual(self.search.line_ids.sorted('sequence'), cheap | cheap_google_expensive | unknown)

    def test_form_view_has_both_views_of_the_results(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertIn('name="results_view"', arch)
        self.assertIn('name="line_table_ids"', arch)
