# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestClientComparison(TransactionCase):
    """Comparativa para el cliente: menú y precio por persona de cada restaurante con presupuesto confirmado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo comparativa'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 40,
        })

    def _restaurant(self, name, **extra):
        vals = {'name': name, 'is_restaurant': True, 'city': 'Málaga'}
        vals.update(extra)
        return self.env['res.partner'].create(vals)

    def _line(self, partner, etiqueta='presupuesto_recibido', amount=1000.0, **extra):
        vals = {
            'search_id': self.search.id, 'source': 'partner', 'name': partner.name,
            'partner_id': partner.id, 'etiqueta': etiqueta, 'quote_amount': amount,
        }
        vals.update(extra)
        return self.env['restagrup.restaurant.search.line'].create(vals)

    def _menu(self, partner, name='Menú grupo', price=25.0):
        return self.env['restagrup.restaurant.menu'].create({
            'name': name, 'partner_id': partner.id, 'cost_price': price,
            'line_ids': [(0, 0, {'course': 'principal', 'name': 'Arroz del señorito'})],
        })

    def test_price_per_person_is_client_price_divided_by_pax(self):
        line = self._line(self._restaurant('Casa A'), amount=1000.0)
        # 1000 € + 20 % = 1200 € para 40 personas
        self.assertEqual(line.quote_client_price_per_person, 30.0)

    def test_price_per_person_is_zero_without_pax(self):
        self.search.min_capacity = 0
        line = self._line(self._restaurant('Casa A'))
        self.assertEqual(line.quote_client_price_per_person, 0.0)

    def test_rows_only_include_confirmed_quotes(self):
        confirmed = self._line(self._restaurant('Confirmado'))
        self._line(self._restaurant('Sin confirmar'), etiqueta='solicitado')
        self._line(self._restaurant('Descartado'), etiqueta='descartado')
        self._line(self._restaurant('Sin importe'), amount=0.0)
        rows = self.search.restagrup_comparison_rows()
        self.assertEqual([row['line'] for row in rows], [confirmed])

    def test_rows_are_sorted_cheapest_first(self):
        expensive = self._line(self._restaurant('Caro'), amount=2000.0)
        cheap = self._line(self._restaurant('Barato'), amount=800.0)
        rows = self.search.restagrup_comparison_rows()
        self.assertEqual([row['line'] for row in rows], [cheap, expensive])

    def test_rows_never_expose_restaurant_cost_or_margin(self):
        self._line(self._restaurant('Casa A'), amount=1000.0)
        row = self.search.restagrup_comparison_rows()[0]
        self.assertEqual(row['price_per_person'], 30.0)
        self.assertNotIn('total', row)  # el presupuesto da precio por menú; el total llega con la confirmación
        self.assertNotIn('quote_amount', row)
        self.assertNotIn('margin', row)

    def test_row_carries_the_chosen_menu_text(self):
        restaurant = self._restaurant('Casa A')
        menu = self._menu(restaurant)
        self._line(restaurant, menu_id=menu.id)
        row = self.search.restagrup_comparison_rows()[0]
        self.assertEqual(row['menu'], menu)
        self.assertIn('Arroz del señorito', row['menu_text'])

    def test_row_menu_text_never_shows_the_restaurant_menu_price(self):
        restaurant = self._restaurant('Casa A')
        menu = self._menu(restaurant, price=27.35)
        self._line(restaurant, menu_id=menu.id)
        row = self.search.restagrup_comparison_rows()[0]
        self.assertNotIn('27.35', row['menu_text'])
        self.assertNotIn('27.35', menu.display_text)  # ni el texto del menú lleva el coste del restaurante
        self.assertIn('32.82', menu.display_text)  # sí el precio de venta (27,35 + 20 %)
        self.assertIn('Arroz del señorito', row['menu_text'])

    def test_row_without_menu_has_empty_menu_text(self):
        self._line(self._restaurant('Casa A'))
        row = self.search.restagrup_comparison_rows()[0]
        self.assertFalse(row['menu'])
        self.assertEqual(row['menu_text'], '')

    def test_menu_must_belong_to_the_line_restaurant(self):
        other_menu = self._menu(self._restaurant('Otra casa'))
        with self.assertRaises(ValidationError):
            self._line(self._restaurant('Casa A'), menu_id=other_menu.id)

    def test_restaurant_is_visible_by_default(self):
        self.assertTrue(self.search.restaurant_visible)
        row_name = self._line(self._restaurant('Casa Visible')).name
        self.assertEqual(self.search.restagrup_comparison_rows()[0]['name'], row_name)

    def test_hidden_restaurant_shows_only_a_numbered_option(self):
        restaurant = self._restaurant('Casa Secreta', city='Cádiz')
        menu = self._menu(restaurant)
        self._line(restaurant, amount=800.0, menu_id=menu.id)
        self._line(self._restaurant('Casa Cara'), amount=2000.0)
        self.search.restaurant_visible = False
        rows = self.search.restagrup_comparison_rows()
        self.assertEqual([row['name'] for row in rows], ['Opción 1', 'Opción 2'])
        self.assertFalse(rows[0]['partner'])
        self.assertIn('Arroz del señorito', rows[0]['menu_text'])  # el menú sigue viéndose

    def test_no_rows_when_nobody_quoted(self):
        self.assertEqual(self.search.restagrup_comparison_rows(), [])
