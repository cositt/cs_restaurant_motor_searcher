# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRestaurantMenu(TransactionCase):
    """Menús estructurados por restaurante: se guardan en la ficha y se reutilizan en las propuestas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.restaurant = cls.env['res.partner'].create({'name': 'Casa Menú', 'is_restaurant': True})

    def _menu(self, **extra):
        vals = {
            'name': 'Menú grupo clásico', 'partner_id': self.restaurant.id,
            'cost_price': 32.0,
            'line_ids': [
                (0, 0, {'course': 'postre', 'name': 'Tarta de queso', 'sequence': 30}),
                (0, 0, {'course': 'entrante', 'name': 'Croquetas caseras', 'allergens': 'gluten, lácteos', 'sequence': 10}),
                (0, 0, {'course': 'principal', 'name': 'Solomillo ibérico', 'sequence': 20}),
            ],
        }
        vals.update(extra)
        return self.Menu.create(vals)

    def test_menu_belongs_to_restaurant_and_counts_on_partner(self):
        self.assertEqual(self.restaurant.restaurant_menu_count, 0)
        menu = self._menu()
        self.assertEqual(self.restaurant.restaurant_menu_ids, menu)
        self.assertEqual(self.restaurant.restaurant_menu_count, 1)

    def test_only_restaurants_can_have_menus(self):
        person = self.env['res.partner'].create({'name': 'Cliente cualquiera'})
        with self.assertRaises(ValidationError):
            self._menu(partner_id=person.id)

    def test_price_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            self._menu(cost_price=-1.0)

    def test_min_pax_cannot_exceed_max_pax(self):
        with self.assertRaises(ValidationError):
            self._menu(min_pax=50, max_pax=20)

    def test_lines_are_ordered_by_course_then_sequence(self):
        menu = self._menu()
        menu.invalidate_recordset(['line_ids'])
        self.assertEqual(menu.line_ids.mapped('course'), ['entrante', 'principal', 'postre'])

    def test_display_text_lists_dishes_by_course_with_price(self):
        menu = self._menu(drinks_included=True, drinks_description='Vino, agua y café')
        text = menu.display_text
        self.assertIn('Menú grupo clásico', text)
        self.assertIn('38.40', text)  # precio de venta: 32 de coste + 20 % de margen
        self.assertNotIn('32.00', text)  # el coste del restaurante no sale
        self.assertLess(text.index('Croquetas caseras'), text.index('Solomillo ibérico'))
        self.assertLess(text.index('Solomillo ibérico'), text.index('Tarta de queso'))
        self.assertIn('gluten, lácteos', text)
        self.assertIn('Vino, agua y café', text)

    def test_description_text_replaces_the_structured_dishes_in_the_text(self):
        menu = self._menu(description='ENTRANTES COMPARTIDOS\nCARNE AL TORO\nPOSTRE DE LA CASA')
        text = menu.display_text
        self.assertIn('CARNE AL TORO', text)
        self.assertNotIn('Croquetas caseras', text)

    def test_description_that_already_covers_the_drinks_is_not_repeated(self):
        menu = self._menu(description='MENÚ\nBEBIDAS INCLUIDAS (vino y agua)', drinks_included=True)
        self.assertNotIn('Bebidas: incluidas', menu.display_text)
        menu.drinks_description = 'Vino de la casa'
        self.assertIn('Bebidas: Vino de la casa', menu.display_text)

    def test_description_is_used_without_price_too(self):
        menu = self._menu(description='MENÚ NAVIDAD')
        text = menu._render_text(with_price=False)
        self.assertIn('MENÚ NAVIDAD', text)
        self.assertNotIn('Croquetas caseras', text)

    def test_blank_description_falls_back_to_the_dishes(self):
        menu = self._menu(description='   \n ')
        self.assertIn('Croquetas caseras', menu.display_text)

    def test_menu_can_have_only_a_description(self):
        menu = self.Menu.create({'name': 'Solo texto', 'partner_id': self.restaurant.id, 'description': 'Paella'})
        self.assertIn('Paella', menu.display_text)

    def test_season_defaults_to_the_current_year(self):
        from odoo import fields
        self.assertEqual(self._menu().season, fields.Date.context_today(self.env.user).year)

    def test_season_must_be_a_plausible_year(self):
        with self.assertRaises(ValidationError):
            self._menu(season=25)  # «25» es la abreviatura: el campo guarda el año completo

    def test_menus_can_be_found_by_city_season_price_and_capacity(self):
        sevilla = self.env['res.partner'].create({'name': 'Casa Sevilla', 'is_restaurant': True, 'city': 'Sevilla'})
        wanted = self.Menu.create({'name': 'A', 'partner_id': sevilla.id, 'season': 2025, 'cost_price': 15.0, 'max_pax': 80})
        self.Menu.create({'name': 'B', 'partner_id': sevilla.id, 'season': 2024, 'cost_price': 15.0, 'max_pax': 80})
        self.Menu.create({'name': 'C', 'partner_id': sevilla.id, 'season': 2025, 'cost_price': 40.0, 'max_pax': 80})
        self.Menu.create({'name': 'D', 'partner_id': sevilla.id, 'season': 2025, 'cost_price': 15.0, 'max_pax': 20})
        found = self.Menu.search([('partner_id.city', 'ilike', 'sevilla'), ('season', '=', 2025),
                                  ('sale_price', '<=', 20.0), ('max_pax', '>=', 50)])
        self.assertEqual(found, wanted)

    def test_search_view_offers_the_clients_filters(self):
        arch = self.Menu.get_view(view_type='search')['arch']
        for expected in ('partner_city', 'season', 'sale_price', 'max_pax'):
            self.assertIn(expected, arch)

    def test_archived_menu_is_not_counted(self):
        menu = self._menu()
        menu.active = False
        self.assertEqual(self.restaurant.restaurant_menu_count, 0)

    def test_duplicate_copies_dishes(self):
        menu = self._menu()
        copy = menu.copy()
        self.assertEqual(len(copy.line_ids), 3)
        self.assertNotEqual(copy.line_ids, menu.line_ids)

    def test_deleting_restaurant_deletes_its_menus(self):
        menu = self._menu()
        self.restaurant.unlink()
        self.assertFalse(menu.exists())

    def test_user_can_manage_menus(self):
        user = self.env['res.users'].create({
            'name': 'Operador', 'login': 'operador_menu', 'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        menu = self.Menu.with_user(user).create({'name': 'Menú rápido', 'partner_id': self.restaurant.id})
        self.assertTrue(menu.with_user(user).read(['name']))


@tagged('post_install', '-at_install')
class TestRestaurantMenuPricing(TransactionCase):
    """Menú como el del CRM del cliente: precio coste + precio venta editable, con el margen del restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.restaurant = cls.env['res.partner'].create({'name': 'Casa Margen', 'is_restaurant': True})
        cls.Menu = cls.env['restagrup.restaurant.menu']

    def _menu(self, **extra):
        vals = {'name': 'Menú', 'partner_id': self.restaurant.id, 'cost_price': 20.0}
        vals.update(extra)
        return self.Menu.create(vals)

    def test_sale_price_defaults_to_cost_plus_global_margin(self):
        self.assertEqual(self._menu().sale_price, 24.0)

    def test_restaurant_with_own_margin_uses_it(self):
        self.restaurant.write({'restaurant_margin_custom': True, 'restaurant_margin_percent': 30.0})
        self.assertEqual(self._menu().sale_price, 26.0)

    def test_restaurant_without_own_margin_follows_the_global_one(self):
        self.restaurant.write({'restaurant_margin_custom': False, 'restaurant_margin_percent': 99.0})
        self.assertEqual(self._menu().sale_price, 24.0)

    def test_sale_price_is_editable_and_sticks(self):
        menu = self._menu()
        menu.sale_price = 27.5
        menu.invalidate_recordset()
        self.assertEqual(menu.sale_price, 27.5)

    def test_sale_price_recomputes_when_cost_changes(self):
        menu = self._menu()
        menu.cost_price = 30.0
        self.assertEqual(menu.sale_price, 36.0)

    def test_profit_percent_is_shown_from_the_actual_prices(self):
        menu = self._menu(sale_price=25.0)
        self.assertEqual(menu.profit_percent, 25.0)

    def test_profit_percent_is_zero_without_cost(self):
        self.assertEqual(self._menu(cost_price=0.0).profit_percent, 0.0)

    def test_menu_type_defaults_to_undefined_and_is_editable(self):
        menu = self._menu()
        self.assertEqual(menu.menu_type, 'sin_definir')
        menu.menu_type = 'buffet'
        self.assertEqual(menu.menu_type, 'buffet')

    def test_pricing_margin_for_a_restaurant(self):
        pricing = self.env['restagrup.pricing']
        self.assertEqual(pricing.margin_percent(partner=self.restaurant), 20.0)
        self.restaurant.write({'restaurant_margin_custom': True, 'restaurant_margin_percent': 15.0})
        self.assertEqual(pricing.margin_percent(partner=self.restaurant), 15.0)
        self.assertAlmostEqual(pricing.apply_margin(100.0, partner=self.restaurant), 115.0)
        self.assertAlmostEqual(pricing.apply_margin(100.0), 120.0)  # sin restaurante, el general

    def test_explicit_percent_wins_over_the_restaurant_margin(self):
        self.restaurant.write({'restaurant_margin_custom': True, 'restaurant_margin_percent': 15.0})
        self.assertAlmostEqual(self.env['restagrup.pricing'].apply_margin(100.0, percent=10.0, partner=self.restaurant), 110.0)

    def test_quote_client_price_uses_the_restaurant_margin(self):
        self.restaurant.write({'restaurant_margin_custom': True, 'restaurant_margin_percent': 10.0})
        lead = self.env['crm.lead'].create({'name': 'Grupo margen'})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'X', 'min_capacity': 10})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Casa Margen', 'partner_id': self.restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 1000.0,
        })
        self.assertEqual(line.quote_client_price, 1100.0)
