# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'
OFFER_KEY = 'restagrup_offer_menu_line_id'


@tagged('post_install', '-at_install')
class TestReunion1311OtherMenu(TransactionCase):
    """Reunión 13/11 (P8): «+ Otro menú» deja elegir entre los menús guardados del restaurante.
    (P10): «Quitar este menú» quita un menú sin perder el restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Frescco Prueba', 'is_restaurant': True, 'is_company': True, 'email': 'frescco@example.com',
            'city': 'Madrid'})
        Menu = cls.env['restagrup.restaurant.menu']
        cls.menu_14 = Menu.create({'name': 'Menú 14', 'partner_id': cls.restaurant.id, 'cost_price': 14})
        cls.menu_12 = Menu.create({'name': 'Menú 12', 'partner_id': cls.restaurant.id, 'cost_price': 12})
        lead = cls.env['crm.lead'].create({'name': 'Grupo otro menú'})
        cls.search = cls.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 40})

    def _line(self, partner=None, menu=None):
        partner = partner or self.restaurant
        line = self.env[LINE].create({
            'search_id': self.search.id, 'source': 'partner', 'name': partner.name, 'partner_id': partner.id,
            'etiqueta': 'interesado'})
        if menu:
            line._apply_catalog_quote(menu)
        return line

    def _cards(self):
        return self.search.line_ids.filtered(lambda line: line.etiqueta != 'descartado')

    # --- P8: + Otro menú ---

    def test_other_menu_offers_only_the_saved_menus_not_yet_used(self):
        line = self._line(menu=self.menu_14)
        action = line.action_offer_other_menu()
        self.assertEqual(action['res_model'], 'restagrup.restaurant.menu')
        self.assertEqual(self.env['restagrup.restaurant.menu'].search(action['domain']), self.menu_12)
        self.assertEqual(action['context'][OFFER_KEY], line.id)

    def test_picking_a_saved_menu_adds_a_card_with_its_catalog_price(self):
        line = self._line(menu=self.menu_14)
        self.menu_12.with_context(**{OFFER_KEY: line.id}).action_offer_this_menu()
        new = self._cards() - line
        self.assertEqual(len(new), 1)
        self.assertEqual(new.menu_id, self.menu_12)
        self.assertEqual(new.quote_price_pp, 12)
        self.assertEqual(new.etiqueta, 'presupuesto_recibido')
        self.assertTrue(new.quote_availability_pending)
        self.assertEqual(line.menu_id, self.menu_14)  # la primera no se toca

    def test_without_free_saved_menus_it_opens_the_register_window(self):
        line = self._line(menu=self.menu_14)
        self._line(menu=self.menu_12)
        action = line.action_offer_other_menu()
        self.assertNotEqual(action.get('res_model'), 'restagrup.restaurant.menu')
        self.assertEqual(len(self._cards()), 3)  # tarjeta en blanco para pegar la respuesta, como antes

    # --- P10: Quitar este menú ---

    def test_removing_a_menu_with_another_card_discards_only_that_card(self):
        first = self._line(menu=self.menu_14)
        second = self._line(menu=self.menu_12)
        second.action_remove_menu()
        self.assertEqual(second.etiqueta, 'descartado')
        self.assertEqual(first.etiqueta, 'presupuesto_recibido')

    def test_removing_the_only_menu_keeps_the_restaurant_as_interested(self):
        line = self._line(menu=self.menu_14)
        action = line.action_remove_menu()
        self.assertEqual(line.etiqueta, 'interesado')
        self.assertFalse(line.menu_id)
        self.assertFalse(line.quote_price_pp)
        self.assertFalse(line.quote_availability_pending)
        self.assertEqual(action['res_model'], 'restagrup.restaurant.menu')  # para elegir otro
        self.assertEqual(action['context'][OFFER_KEY], line.id)

    def test_picking_after_removing_fills_the_same_card(self):
        line = self._line(menu=self.menu_14)
        action = line.action_remove_menu()
        self.menu_12.with_context(**action['context']).action_offer_this_menu()
        self.assertEqual(self._cards(), line)
        self.assertEqual((line.menu_id, line.quote_price_pp, line.etiqueta),
                         (self.menu_12, 12, 'presupuesto_recibido'))

    def test_removing_the_chosen_menu_unchooses_it(self):
        line = self._line(menu=self.menu_14)
        line.action_toggle_chosen()
        self.assertEqual(self.search.chosen_line_id, line)
        line.action_remove_menu()
        self.assertFalse(self.search.chosen_line_id)
