# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestHallazgosGuia1311Dishes(TransactionCase):
    """Hallazgo (5) al capturar la guía en prod (13/11): antes de enviar la confirmación a la agencia o al
    restaurante, el cortafuegos avisa si hay platos elegidos que no están en el menú."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        agency = Partner.create({'name': 'Viajes Guía', 'is_company': True, 'email': 'grupos@guia.example'})
        cls.restaurant = Partner.create({'name': 'Casa Platos', 'is_restaurant': True, 'is_company': True,
                                         'email': 'casa@platos.example', 'city': 'Madrid'})
        menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú Grupos 2027', 'partner_id': cls.restaurant.id, 'line_ids': [
                (0, 0, {'course': 'entrante', 'name': 'Lentejas'}),
                (0, 0, {'course': 'principal', 'name': 'Pollo asado'})]})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Platos', 'partner_id': agency.id})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': '2026-12-15', 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 30})
        cls.line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name, 'menu_id': menu.id,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 15.0,
            'quote_received_date': '2026-11-09 10:00:00', 'agency_choice_notes': '- Lentejas\n- Lubina a la sal'})
        cls.line.action_toggle_chosen()
        cls.lead.action_pass_to_file()
        cls.order = cls.lead._restagrup_live_orders()
        cls.sheet = cls.order.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')

    def test_agency_confirmation_warns_about_dish_not_in_menu(self):
        warning = self.order._fw_dishes_in_menu()
        self.assertTrue(warning)
        self.assertIn('Lubina a la sal', warning)
        self.assertIn('Menú Grupos 2027', warning)

    def test_restaurant_confirmation_warns_about_dish_not_in_menu(self):
        self.assertTrue(self.sheet)
        warning = self.sheet._fw_dishes_in_menu_restaurant()
        self.assertTrue(warning)
        self.assertIn('Lubina a la sal', warning)

    def test_no_warning_when_all_dishes_are_in_the_menu(self):
        self.line.agency_choice_notes = '- Lentejas\n- Pollo asado'
        self.assertFalse(self.order._fw_dishes_in_menu())
        self.assertFalse(self.sheet._fw_dishes_in_menu_restaurant())

    def test_checks_are_active_on_both_confirmations(self):
        Check = self.env['restagrup.firewall.check']
        self.assertEqual(Check.search([('code', '=', 'dishes_in_menu')]).trigger, 'confirm_agency')
        self.assertEqual(Check.search([('code', '=', 'dishes_in_menu_restaurant')]).trigger, 'confirm_restaurant')
