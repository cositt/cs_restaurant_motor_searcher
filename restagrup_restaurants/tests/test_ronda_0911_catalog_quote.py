# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: presupuesto sin esperar al restaurante.

- «Precio de catálogo»: con un menú de su ficha se da el presupuesto aunque el restaurante aún no haya confirmado
  disponibilidad; queda marcado («disponibilidad sin confirmar») para no olvidarlo.
- Presupuesto recibido por WhatsApp o por teléfono: se registra a mano, sin pegar ningún correo.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRonda0911CatalogQuote(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Catálogo', 'is_restaurant': True, 'email': 'catalogo@example.com', 'city': 'Sevilla'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú grupos', 'partner_id': cls.restaurant.id, 'cost_price': 18.0,
            'description': 'Primero: salmorejo\nSegundo: presa'})
        lead = cls.env['crm.lead'].create({'name': 'Grupo catálogo'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 40})

    def _line(self, partner=None):
        partner = partner or self.restaurant
        return self.env[LINE].create({
            'search_id': self.search.id, 'source': 'partner', 'name': partner.name, 'partner_id': partner.id})

    def test_catalog_price_gives_a_quote_without_waiting(self):
        line = self._line()
        line.action_quote_from_catalog()
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')
        self.assertEqual(line.quote_price_pp, 18.0)
        self.assertEqual(line.menu_id, self.menu)
        self.assertTrue(line.quote_received_date)
        self.assertTrue(line.quote_availability_pending)

    def test_catalog_quote_can_be_chosen(self):
        line = self._line()
        line.action_quote_from_catalog()
        line.action_toggle_chosen()
        self.assertEqual(self.search.chosen_line_id, line)

    def test_several_menus_open_the_form_to_pick_one(self):
        self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú infantil', 'partner_id': self.restaurant.id, 'cost_price': 10.0})
        line = self._line()
        action = line.action_quote_from_catalog()
        self.assertEqual(action['res_model'], LINE)
        self.assertEqual(action['res_id'], line.id)
        self.assertTrue(action['context'].get('restagrup_from_catalog'))
        self.assertEqual(line.etiqueta, 'visto')

    def test_picking_the_menu_fills_its_catalog_price(self):
        line = self._line()
        line.menu_id = self.menu
        line._onchange_menu_catalog_price()
        self.assertEqual(line.quote_price_pp, 18.0)

    def test_without_menus_it_says_what_is_missing(self):
        bare = self.env['res.partner'].create({'name': 'Casa sin menús', 'is_restaurant': True})
        with self.assertRaises(UserError):
            self._line(bare).action_quote_from_catalog()

    def test_confirming_availability_clears_the_mark(self):
        line = self._line()
        line.action_quote_from_catalog()
        line.action_confirm_availability()
        self.assertFalse(line.quote_availability_pending)

    def test_a_quote_by_phone_is_registered_by_hand(self):
        line = self._line()
        line.write({'quote_price_pp': 22.0})
        line.action_register_quote()
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')
        self.assertFalse(line.quote_availability_pending)

    def test_card_says_register_quote_and_offers_the_catalog(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertNotIn('Pegar respuesta', arch)
        self.assertIn('Registrar menú', arch)  # reunión 12/11 (5.1)
        self.assertIn('action_quote_from_catalog', arch)
