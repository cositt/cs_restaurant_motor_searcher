# -*- coding: utf-8 -*-
"""El precio estimado del servicio ordena los restaurantes (los más cercanos primero) y avisa de los que se salen
de precio (PPT de Conchita 2026-11-04, diapositiva 2)."""
from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

GOOGLE_PATH = 'odoo.addons.restagrup_restaurants.models.restaurant_search.RestaurantSearch._search_google'


@tagged('post_install', '-at_install')
class TestBudgetSort(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo precio'})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Ronda', 'pax': 30, 'event_date': date(2027, 5, 4),
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id, 'budget_pp': 30.0})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Ronda', 'min_capacity': 30})
        Partner = cls.env['res.partner']
        cls.cheap = Partner.create({'name': 'Barato', 'is_restaurant': True, 'city': 'Ronda', 'restaurant_capacity': 90})
        cls.close = Partner.create({'name': 'Justo', 'is_restaurant': True, 'city': 'Ronda', 'restaurant_capacity': 90})
        cls.dear = Partner.create({'name': 'Caro', 'is_restaurant': True, 'city': 'Ronda', 'restaurant_capacity': 90})
        cls.unknown = Partner.create({'name': 'Sin menús', 'is_restaurant': True, 'city': 'Ronda',
                                      'restaurant_capacity': 90})
        Menu = cls.env['restagrup.restaurant.menu']
        for partner, sale in ((cls.cheap, 15.0), (cls.close, 31.0), (cls.dear, 48.0)):
            Menu.create({'name': 'Menú %s' % partner.name, 'partner_id': partner.id, 'cost_price': sale / 1.2,
                         'sale_price': sale})

    def _results(self):
        with patch(GOOGLE_PATH, return_value=[]):
            self.search.action_search()
        return self.search.line_ids.sorted('sequence')

    def test_estimated_price_is_shown_on_the_search(self):
        self.assertEqual(self.search.budget_pp, 30.0)

    def test_results_are_ordered_by_closeness_to_the_estimate(self):
        names = self._results().mapped('name')
        self.assertEqual(names, ['Justo', 'Barato', 'Caro', 'Sin menús'], 'sin precio conocido, al final')

    def test_restaurants_over_the_estimate_are_flagged(self):
        lines = {line.name: line for line in self._results()}
        self.assertIn('48', lines['Caro'].price_warning)
        self.assertFalse(lines['Justo'].price_warning, '31 € está dentro del margen (15 %)')
        self.assertFalse(lines['Barato'].price_warning, 'más barato no es un problema')
        self.assertFalse(lines['Sin menús'].price_warning)

    def test_a_received_quote_is_the_price_that_counts(self):
        line = self._results().filtered(lambda l: l.name == 'Barato')
        line.quote_price_pp = 40.0  # 48 € a la agencia con el 20 % por defecto
        self.assertAlmostEqual(line.known_price_pp, 48.0)
        self.assertTrue(line.price_warning)

    def test_sort_option_is_available(self):
        self.assertIn('budget_near', dict(self.search._fields['sort_by'].selection))

    def test_without_estimate_nothing_is_flagged(self):
        self.search.event_id = False
        lines = self._results()
        self.assertFalse(self.search.budget_pp)
        self.assertFalse(any(lines.mapped('price_warning')))

    def test_card_shows_the_price_warning(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertIn('record.price_warning', arch)
