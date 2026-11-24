# -*- coding: utf-8 -*-
"""Reunión 23/11: tarjetas de restaurante más claras.
- «Ver menús» se ve coloreado cuando el restaurante tiene menús y apagado cuando no.
- «Registrar menú» no desaparece al tener presupuesto (se pueden registrar varios menús).
- El nombre del restaurante abre su ficha."""
from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReunion2311Cards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        arch = cls.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        cls.root = etree.fromstring(arch.encode())

    def _buttons(self, name):
        return self.root.xpath('//button[@name="%s"] | //a[@name="%s"]' % (name, name))

    def test_view_menus_is_colored_when_the_restaurant_has_menus(self):
        cards = [b for b in self._buttons('action_view_menus') if b.get('t-attf-class')]
        self.assertTrue(cards, 'el botón de la tarjeta debe cambiar de clase según partner_menu_count')
        self.assertIn('partner_menu_count', cards[0].get('t-attf-class'))

    def test_register_menu_stays_after_the_quote_is_received(self):
        buttons = [b for b in self._buttons('action_open_quote_form') if b.get('t-if') is not None
                   or b.get('class', '').startswith('btn btn-outline-primary')]
        card_buttons = [b for b in buttons if 'Registrar menú' in ''.join(b.itertext())]
        self.assertTrue(card_buttons)
        for button in card_buttons:
            self.assertNotIn('presupuesto_recibido', button.get('t-if') or '')

    def test_card_name_opens_the_restaurant_file(self):
        links = [a for a in self._buttons('action_open_restaurant') if a.get('t-if')]
        self.assertTrue(links, 'el nombre de la tarjeta debe llevar a la ficha cuando hay restaurante en Odoo')
        self.assertIn('partner_id', links[0].get('t-if'))

    # --- borde llamativo en los restaurantes en los que hay interés (pedido 23/11) ---

    def _markers(self):
        return self.root.xpath('//*[contains(@class, "o_restagrup_interested_marker")]')

    def test_interested_restaurants_carry_a_marker_for_the_border(self):
        markers = self._markers()
        self.assertTrue(markers, 'la tarjeta lleva una marca que el CSS convierte en borde')
        condition = markers[0].get('t-if') or ''
        for state in ('interesado', 'solicitado', 'presupuesto_recibido'):
            self.assertIn(state, condition)
        for state in ('visto', 'descartado', 'cancelado'):
            self.assertNotIn(state, condition, '%s no es un restaurante en el que haya interés' % state)

    def test_the_border_rule_exists_in_the_stylesheet(self):
        from odoo.tools import file_open
        with file_open('restagrup_restaurants/static/src/css/restaurant_search_kanban.css') as css:
            content = css.read()
        self.assertIn(':has(.o_restagrup_interested_marker)', content)
