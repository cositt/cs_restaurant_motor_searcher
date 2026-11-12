# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestOfferOtherMenu(TransactionCase):
    """Reunión 12/11 (5.7): ofrecer en la propuesta dos menús del mismo restaurante. Una línea por menú, cada una
    con su precio (5.6: registrar el 2.º menú pisaba el precio del 1.º)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Ribs Abada', 'is_restaurant': True, 'email': 'ribs@example.com'})
        Menu = cls.env['restagrup.restaurant.menu']
        cls.weekday = Menu.create({'name': 'Menú grupos 2026 lunes a viernes', 'partner_id': cls.restaurant.id,
                                   'cost_price': 18.0})
        cls.weekend = Menu.create({'name': 'Menú grupos fin de semana 2026', 'partner_id': cls.restaurant.id,
                                   'cost_price': 24.0})
        lead = cls.env['crm.lead'].create({'name': 'Grupo dos menús'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 20})
        cls.line = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'menu_id': cls.weekday.id,
            'quote_price_pp': 18.0, 'quote_received_date': '2026-11-12 10:00:00'})

    def _offer(self):
        action = self.line.action_offer_other_menu()
        self.assertEqual(action['res_model'], LINE)
        return self.env[LINE].browse(action['res_id'])

    def test_creates_a_second_line_of_the_same_restaurant_without_menu(self):
        new = self._offer()
        self.assertNotEqual(new, self.line)
        self.assertEqual(new.partner_id, self.restaurant)
        self.assertEqual(new.search_id, self.search)
        self.assertFalse(new.menu_id)
        self.assertFalse(new.quote_price_pp)
        self.assertEqual(self.line.menu_id, self.weekday)
        self.assertEqual(self.line.quote_price_pp, 18.0)

    def test_new_line_gets_no_reminder_nor_bulk_request(self):
        new = self._offer()
        self.assertNotIn(new.etiqueta, ('solicitado', 'interesado'))

    def test_both_menus_reach_the_proposal_with_their_own_price(self):
        new = self._offer()
        new.write({'menu_id': self.weekend.id, 'quote_price_pp': 24.0})
        new.action_register_quote()
        rows = self.search.restagrup_comparison_rows()
        menus = {row['menu'] for row in rows}
        self.assertEqual(menus, {self.weekday, self.weekend})
        self.assertEqual(self.line.quote_price_pp, 18.0, 'el primer menú conserva su precio')

    def test_needs_the_restaurant_as_contact(self):
        google = self.env[LINE].create({'search_id': self.search.id, 'source': 'google', 'name': 'Sin ficha'})
        with self.assertRaises(UserError):
            google.action_offer_other_menu()

    def test_card_has_the_button(self):
        arch = self.env['restagrup.restaurant.search'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('name="action_offer_other_menu"', arch)
