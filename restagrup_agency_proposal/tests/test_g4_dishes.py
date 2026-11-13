# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestG4Dishes(TransactionCase):
    """Reunión 12/11 (8.5): lo que la agencia elige en el enlace se compara con el menú: las erratas de un plato
    reconocible se corrigen y lo que no está en el menú se avisa."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Ribs G4', 'is_restaurant': True, 'email': 'ribs-g4@example.com', 'city': 'Madrid'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú Estudiantes 2027', 'partner_id': cls.restaurant.id, 'line_ids': [
                (0, 0, {'course': 'entrante', 'name': 'Sopa de fideos'}),
                (0, 0, {'course': 'entrante', 'name': 'Lentejas'}),
                (0, 0, {'course': 'principal', 'name': 'Pollo asado'}),
                (0, 0, {'course': 'principal', 'name': 'Flamenquín'}),
                (0, 0, {'course': 'postre', 'name': 'Helado'})]})
        agency = cls.env['res.partner'].create({'name': 'Agencia G4', 'is_company': True, 'email': 'a@g4.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo G4 platos', 'partner_id': agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 42})
        cls.line = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'menu_id': cls.menu.id, 'etiqueta': 'presupuesto_recibido',
            'quote_price_pp': 14.0, 'quote_received_date': '2026-11-09 10:00:00'})

    def _notes(self, text):
        return self.lead.message_ids.filtered(lambda m: text in (m.body or ''))

    def test_dishes_of_the_menu_are_kept_as_written(self):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, '- Sopa de fideos\r\n- Flamenquín')
        self.assertEqual(self.line.agency_choice_notes, '- Sopa de fideos\n- Flamenquín')
        self.assertFalse(self._notes('no está en el menú'))

    def test_typos_are_corrected_to_the_menu_dish(self):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, '- sopa de fidos\n- Flamenquin\n- Pollo')
        self.assertEqual(self.line.agency_choice_notes, '- Sopa de fideos\n- Flamenquín\n- Pollo asado')
        self.assertTrue(self._notes('sopa de fidos'))

    def test_dish_not_in_the_menu_is_warned(self):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, '- Lentejas\n- Lubina a la sal')
        self.assertIn('Lubina a la sal', self.line.agency_choice_notes)
        warning = self._notes('no está en el menú')
        self.assertTrue(warning)
        self.assertIn('Lubina a la sal', warning[0].body)
        self.assertIn('Menú Estudiantes 2027', warning[0].body)

    def test_without_menu_nothing_is_checked(self):
        self.line.menu_id = False
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, 'Lubina; 2 celiacos')
        self.assertEqual(self.line.agency_choice_notes, 'Lubina; 2 celiacos')
        self.assertFalse(self._notes('no está en el menú'))
