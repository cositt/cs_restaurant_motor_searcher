# -*- coding: utf-8 -*-
"""Ticket de Conchita 24/11 (punto 5): el menú de un restaurante extranjero enseña el coste en SU moneda, con el
nombre de la moneda bien visible, y también en euros junto a la venta (ficha del menú y «ojo»)."""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

FETCH = 'odoo.addons.restagrup_restaurants.models.exchange.RestagrupExchange._fetch_rates'


@tagged('post_install', '-at_install')
class TestMenuPriceSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('restagrup.default_margin_percent', '20')
        set_param('restagrup.foreign_margin_percent', '25')
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.env.company.country_id = cls.env.ref('base.es')
        cls.madrid = cls.env['res.partner'].create({
            'name': 'Casa Lucio Resumen', 'is_restaurant': True, 'is_company': True, 'city': 'Madrid',
            'country_id': cls.env.ref('base.es').id})
        cls.londres = cls.env['res.partner'].create({
            'name': 'Pub Londres Resumen', 'is_restaurant': True, 'is_company': True, 'city': 'Londres',
            'country_id': cls.env.ref('base.uk').id, 'restaurant_currency_code': 'GBP'})

    def _menu(self, partner, cost):
        return self.Menu.create({'name': 'Menú grupos', 'partner_id': partner.id, 'cost_price': cost})

    def test_foreign_menu_shows_local_currency_name_euros_and_sale(self):
        menu = self._menu(self.londres, 20.0)
        with patch(FETCH, return_value={'GBP': 0.8}):  # 1 EUR = 0.8 GBP -> 1 GBP = 1.25 EUR
            menu.action_convert_to_eur()
        summary = menu.price_summary
        self.assertIn('20,00', summary)
        self.assertIn('GBP', summary)
        self.assertIn('25,00', summary)  # coste en euros
        self.assertIn('31,25', summary)  # venta: 25 € + 25 %
        self.assertIn('€', summary)

    def test_foreign_menu_not_converted_says_so(self):
        summary = self._menu(self.londres, 20.0).price_summary
        self.assertIn('GBP', summary)
        self.assertIn('sin convertir', summary)

    def test_euro_menu_summary_has_no_conversion_part(self):
        summary = self._menu(self.madrid, 20.0).price_summary
        self.assertIn('20,00', summary)
        self.assertNotIn('GBP', summary)
        self.assertNotIn('sin convertir', summary)
        self.assertIn('24,00', summary)  # venta: 20 € + 20 %

    def test_summary_is_not_stored_and_follows_the_price(self):
        menu = self._menu(self.madrid, 20.0)
        menu.cost_price = 30.0
        self.assertIn('30,00', menu.price_summary)
