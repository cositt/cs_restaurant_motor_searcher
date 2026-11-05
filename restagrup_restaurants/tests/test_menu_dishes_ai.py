# -*- coding: utf-8 -*-
"""Menús con la descripción escrita pero sin platos: señal «Platos sin completar» y botón que los rellena con la
IA a partir de la descripción, uno o varios a la vez (idea de Juan sobre el PPT de Conchita 2026-11-04, diap. 6)."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
DESCRIPTION = 'ENTRANTES\nSalmorejo cordobés\nPRINCIPAL\nMerluza en salsa verde\nPOSTRE\nTocino de cielo'
DISHES = {'platos': [
    {'tipo': 'entrante', 'nombre': 'Salmorejo cordobés'},
    {'tipo': 'principal', 'nombre': 'Merluza en salsa verde'},
    {'tipo': 'postre', 'nombre': 'Tocino de cielo'},
    {'tipo': 'sobremesa', 'nombre': 'Chupito de orujo'},
    {'tipo': 'postre', 'nombre': '  '},
]}


@tagged('post_install', '-at_install')
class TestMenuDishesAi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({'name': 'Mesón Platos', 'is_restaurant': True})

    def _menu(self, **vals):
        return self.env['restagrup.restaurant.menu'].create(dict({
            'name': 'Menú grupos', 'partner_id': self.restaurant.id, 'cost_price': 25.0,
            'description': DESCRIPTION}, **vals))

    def _complete(self, menus, response=DISHES):
        with patch(LLM, return_value=(response, 'groq')):
            return menus.action_complete_dishes_ai()

    def test_menu_with_description_and_no_dishes_is_flagged(self):
        self.assertTrue(self._menu().dishes_missing)
        self.assertFalse(self._menu(description=False).dishes_missing, 'sin descripción no hay de dónde sacar')
        with_dishes = self._menu(line_ids=[(0, 0, {'course': 'principal', 'name': 'Paella'})])
        self.assertFalse(with_dishes.dishes_missing)

    def test_ai_fills_the_dishes_from_the_description(self):
        menu = self._menu()
        self._complete(menu)
        self.assertEqual(menu.line_ids.mapped('name'),
                         ['Salmorejo cordobés', 'Merluza en salsa verde', 'Tocino de cielo', 'Chupito de orujo'])
        self.assertEqual(menu.line_ids.mapped('course'), ['entrante', 'principal', 'postre', 'otro'])
        self.assertEqual(menu.description, DESCRIPTION, 'la descripción no se toca')
        self.assertFalse(menu.dishes_missing)
        self.assertFalse(menu.ai_pending_review, 'sale de lo que ya escribió una persona: no pasa a revisión')

    def test_it_is_recorded_in_ai_activity(self):
        menu = self._menu()
        self._complete(menu)
        log = self.env['restagrup.ai.log'].search(
            [('source_model', '=', menu._name), ('source_res_id', '=', menu.id)], limit=1)
        self.assertEqual((log.kind, log.state), ('menu_dishes', 'auto'))

    def test_several_menus_at_once(self):
        menus = self._menu() | self._menu(name='Menú 2')
        self._complete(menus)
        self.assertEqual(menus.mapped('dishes_missing'), [False, False])

    def test_menus_that_already_have_dishes_are_left_alone(self):
        menu = self._menu(line_ids=[(0, 0, {'course': 'principal', 'name': 'Paella'})])
        self._complete(menu | self._menu())
        self.assertEqual(menu.line_ids.mapped('name'), ['Paella'])

    def test_without_ai_answer_it_says_so(self):
        with self.assertRaises(UserError):
            self._complete(self._menu(), response=None)

    def test_screens_offer_the_button_and_the_flag(self):
        Menu = self.env['restagrup.restaurant.menu']
        form = Menu.get_view(view_type='form')['arch']
        self.assertIn('name="action_complete_dishes_ai"', form)
        self.assertIn('dishes_missing', form)
        listing = Menu.get_view(view_type='list')['arch']
        self.assertIn('dishes_missing', listing)
