# -*- coding: utf-8 -*-
"""Desde la tarjeta del buscador: ver los menús del restaurante (coste y venta) y pedir disponibilidad de uno
concreto, que va en el correo con sus platos y su precio de coste (PPT de Conchita 2026-11-04, diapositiva 5)."""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMenuPick(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Menús', 'is_restaurant': True, 'email': 'reservas@meson.example.com'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú Senior', 'partner_id': cls.restaurant.id, 'cost_price': 24.5, 'sale_price': 29.4,
            'description': 'Salmorejo\nMerluza\nTocino de cielo'})
        cls.other = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú Otro', 'partner_id': cls.env['res.partner'].create(
                {'name': 'Otro', 'is_restaurant': True}).id, 'cost_price': 10})
        lead = cls.env['crm.lead'].create({'name': 'Grupo menús'})
        search = cls.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Sevilla'})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'email': cls.restaurant.email})

    def test_view_menus_shows_only_this_restaurant_with_cost_and_sale(self):
        action = self.line.action_view_menus()
        menus = self.env['restagrup.restaurant.menu'].search(action['domain'])
        self.assertEqual(menus, self.menu)
        self.assertEqual(action['context']['restagrup_search_line_id'], self.line.id)
        view = self.env.ref('restagrup_restaurants.view_restaurant_menu_pick_list')
        arch = self.env['restagrup.restaurant.menu'].get_view(view_id=view.id)['arch']
        for name in ('cost_price', 'sale_price', 'action_request_quote_with_menu'):
            self.assertIn(name, arch)

    def test_request_availability_of_a_specific_menu(self):
        self.menu.with_context(restagrup_search_line_id=self.line.id).action_request_quote_with_menu()
        self.assertEqual(self.line.menu_id, self.menu)
        self.assertEqual(self.line.etiqueta, 'solicitado')
        message = self.line.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        self.assertIn('Merluza', message.body)
        self.assertIn('24,50', message.body, 'al restaurante, su precio de coste')
        self.assertNotIn('29,40', message.body, 'nunca nuestro precio de venta')

    def test_card_has_the_view_menus_button(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertIn('name="action_view_menus"', arch.split('<t t-name="card">')[1])
