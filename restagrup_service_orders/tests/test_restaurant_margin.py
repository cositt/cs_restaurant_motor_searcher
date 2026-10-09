# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

MARGIN_PARAM = 'restagrup.default_margin_percent'
LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRestaurantMargin(TransactionCase):
    """El margen de cada restaurante (si lo tiene) manda sobre el general en todo el circuito de venta."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(MARGIN_PARAM, '20')
        cls.client = cls.env['res.partner'].create({'name': 'Agencia margen', 'email': 'ag@example.com'})
        cls.own = cls.env['res.partner'].create({
            'name': 'Con margen propio', 'is_restaurant': True, 'email': 'own@example.com',
            'restaurant_margin_custom': True, 'restaurant_margin_percent': 10.0,
        })
        cls.plain = cls.env['res.partner'].create({
            'name': 'Sin margen propio', 'is_restaurant': True, 'email': 'plain@example.com',
        })
        cls.reason = cls.env.ref('restagrup_core.cancel_reason_cheaper')

    def _menu(self, restaurant, cost=25.0):
        return self.env['product.template'].create({
            'name': 'Menú %s' % restaurant.name, 'type': 'service', 'standard_price': cost,
            'sale_ok': True, 'restaurant_id': restaurant.id,
        })

    def _menu_order(self, restaurant, qty=40):
        product = self._menu(restaurant).product_variant_id
        return self.env['sale.order'].create({
            'partner_id': self.client.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})],
        })

    def _search(self, pax=30):
        lead = self.env['crm.lead'].create({'name': 'Grupo margen', 'partner_id': self.client.id})
        return self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Toledo', 'min_capacity': pax})

    def _quote(self, search, restaurant, amount):
        return self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': amount})

    def test_menu_product_client_price_uses_the_restaurant_margin(self):
        self.assertAlmostEqual(self._menu(self.own).restagrup_client_price, 27.5)
        self.assertAlmostEqual(self._menu(self.plain).restagrup_client_price, 30.0)

    def test_menu_product_price_follows_a_later_margin_change(self):
        menu = self._menu(self.own)
        self.own.restaurant_margin_percent = 40.0
        self.assertAlmostEqual(menu.restagrup_client_price, 35.0)

    def test_menu_order_line_uses_the_restaurant_margin_and_freezes_it(self):
        line = self._menu_order(self.own).order_line
        self.assertAlmostEqual(line.price_unit, 27.5)
        self.assertEqual(line.restagrup_margin_pct, 10.0)
        self.own.restaurant_margin_percent = 50.0
        line.product_uom_qty = 50
        self.assertEqual(line.restagrup_margin_pct, 10.0)
        self.assertAlmostEqual(line.price_unit, 27.5)

    def test_menu_order_line_without_own_margin_keeps_the_general_one(self):
        line = self._menu_order(self.plain).order_line
        self.assertAlmostEqual(line.price_unit, 30.0)
        self.assertEqual(line.restagrup_margin_pct, 20.0)

    def test_quote_order_line_uses_the_restaurant_margin(self):
        search = self._search(pax=30)
        line = self._quote(search, self.own, 1000.0)
        line.action_toggle_chosen()
        search.action_create_sale_order()
        order_line = search.sale_order_id.order_line
        self.assertAlmostEqual(order_line.price_unit * order_line.product_uom_qty, 1100.0, places=1)
        self.assertEqual(order_line.restagrup_margin_pct, 10.0)

    def test_changing_restaurant_applies_the_new_restaurants_margin(self):
        search = self._search(pax=30)
        old = self._quote(search, self.plain, 1000.0)
        new = self._quote(search, self.own, 800.0)
        old.action_toggle_chosen()
        search.action_create_sale_order()
        wizard = self.env['restagrup.restaurant.change.wizard'].create({
            'search_id': search.id, 'reason_id': self.reason.id, 'notify_restaurant': False,
            'replacement_line_id': new.id,
        })
        wizard.action_confirm()
        order_line = search.sale_order_id.order_line
        self.assertAlmostEqual(order_line.price_unit * order_line.product_uom_qty, 880.0, places=1)
        self.assertEqual(order_line.restagrup_margin_pct, 10.0)
