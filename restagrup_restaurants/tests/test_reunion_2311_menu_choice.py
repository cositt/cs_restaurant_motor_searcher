# -*- coding: utf-8 -*-
"""Reunión 23/11: en «Revisar y enviar» de «Pedir presupuesto» hay un desplegable con los menús del restaurante.
Elegir uno escribe sus platos y su precio de coste en {menu}; sin elegir, {menu} queda vacío. Al enviar, el menú
queda en la tarjeta."""
from odoo.tests.common import TransactionCase, tagged

WIZARD = 'restagrup.send.wizard'


@tagged('post_install', '-at_install')
class TestReunion2311MenuChoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa dos menús', 'is_restaurant': True, 'email': 'dos@menus.example', 'city': 'Madrid'})
        cls.menu_a = cls._menu('Menú Peregrino', 'Sopa castellana', 16.0)
        cls.menu_b = cls._menu('Menú Grupos', 'Lentejas', 21.0)
        lead = cls.env['crm.lead'].create({'name': 'Grupo dos menús'})
        search = cls.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 30})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name, 'partner_id': cls.restaurant.id})

    @classmethod
    def _menu(cls, name, dish, cost):
        return cls.env['restagrup.restaurant.menu'].create({
            'name': name, 'partner_id': cls.restaurant.id, 'cost_price': cost,
            'line_ids': [(0, 0, {'course': 'entrante', 'name': dish})]})

    def _wizard(self):
        action = self.line.action_open_quote_request()
        return self.env[WIZARD].browse(action['res_id'])

    def _choose(self, wizard, menu):
        wizard.menu_id = menu
        wizard._onchange_menu_id()

    def test_the_dropdown_offers_the_menus_of_that_restaurant(self):
        wizard = self._wizard()
        self.assertEqual(wizard.menu_partner_id, self.restaurant)
        self.assertFalse(wizard.menu_id)

    def test_without_a_menu_the_variable_is_empty(self):
        self.assertNotIn('Sopa castellana', self._wizard().body)

    def test_choosing_a_menu_writes_its_dishes_and_cost_price(self):
        wizard = self._wizard()
        self._choose(wizard, self.menu_a)
        self.assertIn('Sopa castellana', wizard.body)
        self.assertIn('16', wizard.body)

    def test_changing_the_menu_replaces_the_previous_one(self):
        wizard = self._wizard()
        self._choose(wizard, self.menu_a)
        self._choose(wizard, self.menu_b)
        self.assertIn('Lentejas', wizard.body)
        self.assertNotIn('Sopa castellana', wizard.body)

    def test_clearing_the_menu_empties_the_variable_again(self):
        wizard = self._wizard()
        self._choose(wizard, self.menu_a)
        self._choose(wizard, self.env['restagrup.restaurant.menu'])
        self.assertNotIn('Sopa castellana', wizard.body)

    def test_sending_keeps_the_chosen_menu_on_the_card(self):
        wizard = self._wizard()
        self._choose(wizard, self.menu_b)
        wizard.action_send()
        self.assertEqual(self.line.menu_id, self.menu_b)
        sent = self.line.message_ids.filtered(lambda m: m.message_type == 'email')
        self.assertIn('Lentejas', sent[:1].body)

    def test_menu_with_no_dropdown_when_the_restaurant_has_no_menus(self):
        lone = self.env['res.partner'].create({'name': 'Sin menús', 'is_restaurant': True, 'email': 's@m.example'})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.line.search_id.id, 'source': 'partner', 'name': lone.name, 'partner_id': lone.id})
        wizard = self.env[WIZARD].browse(line.action_open_quote_request()['res_id'])
        self.assertFalse(wizard.has_menus)
