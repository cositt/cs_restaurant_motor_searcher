# -*- coding: utf-8 -*-
"""Notas de Conchita tras la reunión del 05/11/2026, parte de restaurantes:

- Ficha del restaurante ordenada como su CRM: datos generales (cuenta, Google Maps, zona, ubicación, contrato,
  moneda y precios de referencia) e información adicional.
- Restaurantes en otra moneda: el coste en su moneda, «Convertir a euros» con el cambio del BCE (api.frankfurter.dev,
  el mismo que usa su CRM) y venta con el 25 % fuera de España, también si cobran en euros.
- Barra de búsqueda en las opciones orientativas.
"""
import re
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

FETCH = 'odoo.addons.restagrup_restaurants.models.exchange.RestagrupExchange._fetch_rates'


@tagged('post_install', '-at_install')
class TestReunion0511Restaurants(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('restagrup.default_margin_percent', '20')
        set_param('restagrup.foreign_margin_percent', '25')
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.spain = cls.env.ref('base.es')
        cls.env.company.country_id = cls.spain
        cls.eur = cls.env.ref('base.EUR')
        cls.czk = cls.env.ref('base.CZK')
        cls.madrid = cls.env['res.partner'].create({
            'name': 'Casa Lucio Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Madrid',
            'country_id': cls.spain.id, 'restaurant_capacity': 80})
        cls.braga = cls.env['res.partner'].create({
            'name': 'Tasquinha Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Braga',
            'country_id': cls.env.ref('base.pt').id, 'restaurant_capacity': 80})
        cls.praga = cls.env['res.partner'].create({
            'name': 'U Fleků Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Praga',
            'country_id': cls.env.ref('base.cz').id, 'restaurant_currency_code': 'CZK', 'restaurant_capacity': 120})

    def _menu(self, partner, cost, **extra):
        vals = {'name': 'Menú de grupo', 'partner_id': partner.id, 'cost_price': cost, 'menu_type': 'almuerzo'}
        vals.update(extra)
        return self.Menu.create(vals)

    # --- ficha del restaurante (punto 9) ---

    def test_restaurant_has_the_general_data_of_their_crm(self):
        self.madrid.write({
            'restaurant_zone': 'Centro histórico', 'restaurant_location_type': 'centro',
            'restaurant_maps_url': 'https://maps.google.com/?q=casa+lucio', 'restaurant_has_contract': True,
            'restaurant_avg_carta_price': 45.0, 'restaurant_min_menu_price': 22.0,
            'restaurant_weekend_menu_price': 28.0,
        })
        self.assertEqual(self.madrid.restaurant_location_type, 'centro')
        self.assertTrue(self.madrid.restaurant_has_contract)
        self.assertEqual(self.madrid.restaurant_currency_code, 'EUR')

    def test_restaurant_form_groups_general_data_first(self):
        arch = self.env['res.partner'].get_view(self.env.ref('base.view_partner_form').id, 'form')['arch']
        page = arch.split('name="restaurant"', 1)[1].split('</page>', 1)[0]
        general = page.split('name="restaurant_general"', 1)[1]
        additional = page.split('name="restaurant_additional"', 1)[1]
        for field in ('restaurant_iban', 'restaurant_maps_url', 'restaurant_zone', 'restaurant_location_type',
                      'restaurant_has_contract', 'restaurant_currency_code', 'restaurant_min_menu_price'):
            self.assertIn('name="%s"' % field, general.split('name="restaurant_additional"', 1)[0], field)
        self.assertIn('name="restaurant_capacity"', additional)
        self.assertLess(page.index('restaurant_general'), page.index('restaurant_additional'))

    # --- margen: 25 % fuera de España (punto 28) ---

    def test_spanish_restaurant_keeps_twenty_percent(self):
        menu = self._menu(self.madrid, 20.0)
        self.assertAlmostEqual(menu.sale_price, 24.0)

    def test_foreign_restaurant_in_euros_gets_twenty_five_percent(self):
        menu = self._menu(self.braga, 20.0)
        self.assertEqual(menu.currency_id, self.eur)
        self.assertAlmostEqual(menu.sale_price, 25.0)
        self.assertAlmostEqual(self.env['restagrup.pricing'].margin_percent(partner=self.braga), 25.0)

    def test_restaurant_own_margin_still_wins(self):
        self.braga.write({'restaurant_margin_custom': True, 'restaurant_margin_percent': 15.0})
        self.assertAlmostEqual(self._menu(self.braga, 20.0).sale_price, 23.0)

    def test_restaurant_without_country_counts_as_spain(self):
        self.madrid.country_id = False
        self.assertAlmostEqual(self.env['restagrup.pricing'].margin_percent(partner=self.madrid), 20.0)

    # --- moneda extranjera (punto 28) ---

    def test_menu_takes_the_restaurant_currency(self):
        menu = self._menu(self.praga, 500.0)
        self.assertEqual(menu.currency_id, self.czk)
        self.assertTrue(menu.is_foreign_currency)

    def test_foreign_menu_without_rate_has_no_sale_price_yet(self):
        menu = self._menu(self.praga, 500.0)
        self.assertFalse(menu.exchange_rate)
        self.assertEqual(menu.cost_price_eur, 0.0)
        self.assertEqual(menu.sale_price, 0.0)

    def test_convert_to_euros_uses_the_ecb_rate(self):
        menu = self._menu(self.praga, 500.0)
        with patch(FETCH, return_value={'CZK': 25.0}) as fetch:
            menu.action_convert_to_eur()
        fetch.assert_called_once()
        self.assertAlmostEqual(menu.exchange_rate, 0.04)
        self.assertTrue(menu.rate_date)
        self.assertAlmostEqual(menu.cost_price_eur, 20.0)
        self.assertAlmostEqual(menu.sale_price, 25.0)  # 20 € + 25 %
        self.assertAlmostEqual(self.env['restagrup.exchange'].eur_per_unit(self.czk), 0.04)

    def test_convert_to_euros_says_so_when_the_bank_does_not_answer(self):
        menu = self._menu(self.praga, 500.0)
        with patch(FETCH, side_effect=UserError('sin conexión')), self.assertRaises(UserError):
            menu.action_convert_to_eur()

    def test_euro_menu_needs_no_conversion(self):
        menu = self._menu(self.madrid, 20.0)
        self.assertFalse(menu.is_foreign_currency)
        self.assertAlmostEqual(menu.cost_price_eur, 20.0)

    def test_text_for_the_restaurant_keeps_its_own_currency(self):
        menu = self._menu(self.praga, 500.0)
        self.assertIn(self.czk.symbol, menu._render_text_for_restaurant())

    def test_client_text_is_always_in_euros(self):
        menu = self._menu(self.praga, 500.0, exchange_rate=0.04)
        self.assertIn(self.eur.symbol, menu._render_text().splitlines()[0])
        self.assertNotIn(self.czk.symbol, menu._render_text().splitlines()[0])

    def test_cron_refreshes_the_rates_of_the_currencies_in_use(self):
        self._menu(self.praga, 500.0)
        with patch(FETCH, return_value={'CZK': 24.0}) as fetch:
            self.env['restagrup.exchange']._cron_refresh_rates()
        self.assertIn('CZK', fetch.call_args[0][0])
        self.assertAlmostEqual(self.env['restagrup.exchange'].eur_per_unit(self.czk), 1 / 24.0)

    # --- buscador en las opciones orientativas (punto 11) ---

    def test_approx_options_can_be_searched(self):
        self._menu(self.madrid, 20.0, name='Menú cocido')
        self.madrid.restaurant_zone = 'Latina'
        other = self.env['res.partner'].create({
            'name': 'Botín Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Madrid'})
        self._menu(other, 30.0, name='Menú cochinillo')
        lead = self.env['crm.lead'].create({'name': 'Grupo Madrid'})
        self.env['restagrup.lead.event'].create({'lead_id': lead.id, 'city': 'Madrid', 'pax': 40})
        pending = self.env['restagrup.pending.mail'].create({
            'kind': 'lead_data_request', 'request_lead_id': lead.id,
            'recipient_email': 'agencia@example.com', 'subject': 'Datos', 'body': 'Hola'})
        wizard = self.env['restagrup.approx.options.wizard']._create_for(pending)
        self.assertEqual(len(wizard.line_ids), 2)
        for text, expected in (('cochinillo', other), ('latina', self.madrid), ('LUCIO', self.madrid)):
            wizard.search_text = text
            wizard.action_refresh()
            self.assertEqual(wizard.line_ids.partner_id, expected, text)
        arch = self.env['restagrup.approx.options.wizard'].get_view(view_type='form')['arch']
        self.assertTrue(re.search(r'name="search_text"', arch))
