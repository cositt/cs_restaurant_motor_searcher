# -*- coding: utf-8 -*-
"""Ronda 20/11 (2b): editar el menú elegido (postre confirmado por teléfono, cambio de un plato…)."""
from odoo.tests.common import TransactionCase, tagged

WIZARD = 'restagrup.chosen.menu.wizard'


@tagged('post_install', '-at_install')
class TestRonda2011EditChosenMenu(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        restaurant = cls.env['res.partner'].create({
            'name': 'Casa editar 2011', 'is_restaurant': True, 'email': 'editar-2011@example.com', 'city': 'Madrid'})
        agency = cls.env['res.partner'].create({'name': 'Agencia editar', 'is_company': True, 'email': 'a@e.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo editar 2011', 'partner_id': agency.id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 30})
        menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú editar', 'partner_id': restaurant.id,
            'line_ids': [(0, 0, {'course': course, 'name': dish}) for course, dishes in {
                'entrante': ['Sopa', 'Ensalada'], 'principal': ['Pollo', 'Lubina'], 'postre': ['Flan', 'Helado'],
            }.items() for dish in dishes]})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'menu_id': menu.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 14.0,
            'quote_received_date': '2026-11-09 10:00:00', 'agency_choice_notes': '- Sopa\n- Pollo'})

    def _wizard(self, line=None):
        action = (line or self.line).action_edit_chosen_menu()
        self.assertEqual(action['res_model'], WIZARD)
        return self.env[WIZARD].browse(action['res_id'])

    def _selected(self, wizard):
        return sorted(wizard.line_ids.filtered('selected').mapped('name'))

    def test_wizard_preselects_what_the_agency_chose(self):
        self.assertEqual(self._selected(self._wizard()), ['Pollo', 'Sopa'])

    def test_wizard_lists_every_dish_of_the_menu_by_course(self):
        wizard = self._wizard()
        self.assertEqual(len(wizard.line_ids), 6)
        self.assertEqual(wizard.line_ids[-1].course, 'postre')

    def test_adding_the_dessert_updates_the_chosen_notes(self):
        wizard = self._wizard()
        wizard.line_ids.filtered(lambda l: l.name == 'Flan').selected = True
        wizard.action_save()
        self.assertEqual(self.line.agency_choice_notes, '- Sopa\n- Pollo\n- Flan')
        self.assertEqual(self.line._restagrup_missing_courses(), [])

    def test_changing_a_dish_replaces_it(self):
        wizard = self._wizard()
        wizard.line_ids.filtered(lambda l: l.name == 'Pollo').selected = False
        wizard.line_ids.filtered(lambda l: l.name == 'Lubina').selected = True
        wizard.action_save()
        self.assertEqual(self.line.agency_choice_notes, '- Sopa\n- Lubina')

    def test_dishes_outside_the_menu_are_kept_and_can_be_added(self):
        self.line.agency_choice_notes = '- Sopa\n- Pollo\n- Tarta de la abuela'
        wizard = self._wizard()
        self.assertEqual(wizard.extra_text, 'Tarta de la abuela')
        wizard.extra_text = 'Tarta de la abuela\nSin gluten para 2'
        wizard.action_save()
        self.assertEqual(self.line.agency_choice_notes, '- Sopa\n- Pollo\n- Tarta de la abuela\n- Sin gluten para 2')

    def test_saving_logs_the_change_on_the_group(self):
        wizard = self._wizard()
        wizard.line_ids.filtered(lambda l: l.name == 'Helado').selected = True
        wizard.action_save()
        bodies = ' '.join(self.lead.message_ids.mapped('body'))
        self.assertIn('Helado', bodies)
        self.assertIn('Menú elegido', bodies)

    def test_saving_with_a_course_still_missing_warns(self):
        wizard = self._wizard()
        wizard.action_save()
        notes = ' '.join(self.lead.message_ids.mapped('body'))
        self.assertIn('Falta elegir', notes)

    def test_no_change_logs_nothing(self):
        before = len(self.lead.message_ids)
        self._wizard().action_save()
        self.assertEqual(len(self.lead.message_ids), before + 1)  # solo el aviso de «Falta elegir: postre»

    def test_menu_without_dishes_edits_free_text(self):
        bare = self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.line.search_id.id, 'source': 'google', 'name': 'Sin menú 2011',
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 12.0, 'quote_received_date': '2026-11-09 10:00:00',
            'agency_choice_notes': 'Menú del día'})
        wizard = self._wizard(bare)
        self.assertFalse(wizard.line_ids)
        wizard.extra_text = 'Menú del día\nPostre: flan'
        wizard.action_save()
        self.assertEqual(bare.agency_choice_notes, '- Menú del día\n- Postre: flan')
