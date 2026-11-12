# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11 (Conchita): «El 3 de Oro» no salía al buscar en Sevilla, ni filtrando por «oro».

- Un restaurante dado de alta a mano sin aforo (0 = desconocido) quedaba fuera con «Aforo mínimo 42». Sin dato no se
  descarta: sale, y ya lo valora quien busca.
- Al volver a buscar con un nombre, lo encontrado se añadía al final (después de 66 resultados) y no se veía. Ahora lo
  que coincide con el nombre sube arriba del todo.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

GOOGLE_PATH = 'odoo.addons.restagrup_restaurants.models.restaurant_search.RestaurantSearch._search_google'


@tagged('post_install', '-at_install')
class TestRonda1111Search(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lead = cls.env['crm.lead'].create({'name': 'Grupo adulto'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 42})
        cls.arcos = cls.env['res.partner'].create({
            'name': 'Mesón Arcos Test', 'is_restaurant': True, 'city': 'Sevilla', 'restaurant_capacity': 150})
        cls.oro = cls.env['res.partner'].create({
            'name': 'El 3 de Oro Test', 'is_restaurant': True, 'city': 'Sevilla'})
        cls.small = cls.env['res.partner'].create({
            'name': 'Tasca Pequeña Test', 'is_restaurant': True, 'city': 'Sevilla', 'restaurant_capacity': 20})

    def _run(self):
        with patch(GOOGLE_PATH, return_value=[]):
            self.search.action_search()

    def test_restaurant_without_capacity_is_not_left_out(self):
        self._run()
        partners = self.search.line_ids.partner_id
        self.assertIn(self.oro, partners)
        self.assertIn(self.arcos, partners)
        self.assertNotIn(self.small, partners)

    def test_restaurant_without_price_level_is_not_left_out(self):
        self.search.max_price_level = '2'
        self._run()
        self.assertIn(self.oro, self.search.line_ids.partner_id)

    def test_searching_again_by_name_puts_the_match_on_top(self):
        self.search.restaurant_name = 'Arcos Test'
        self._run()
        self.search.restaurant_name = 'oro'
        self._run()
        first = self.search.line_ids.sorted('sequence')[:1]
        self.assertEqual(first.partner_id, self.oro)
