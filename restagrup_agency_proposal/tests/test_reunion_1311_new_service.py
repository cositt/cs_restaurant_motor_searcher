# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion1311NewService(TransactionCase):
    """Reunión 13/11 (P7): un servicio que se añade a un grupo ya en Expediente sigue su propio proceso (propuesta,
    elegir, presupuesto adicional) sin tocar lo ya cerrado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        agency = Partner.create({'name': 'Viajes Segundo', 'is_company': True, 'email': 'grupos@segundo.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Dos Días', 'partner_id': agency.id})
        cls.first_line = cls._service('2026-12-14', 'Frescco Prueba', 14.0)
        cls.first_line.action_toggle_chosen()
        cls.lead.action_pass_to_file()
        cls.first_order = cls.lead._restagrup_live_orders()
        cls.second_line = cls._service('2026-12-16', 'Ribs Prueba', 10.0)
        cls.second_search = cls.second_line.search_id

    @classmethod
    def _service(cls, date, restaurant_name, price):
        restaurant = cls.env['res.partner'].create({
            'name': restaurant_name, 'is_restaurant': True, 'is_company': True,
            'email': '%s@rest.example' % restaurant_name.split()[0].lower(), 'city': 'Madrid'})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 50, 'event_date': date, 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 50})
        return cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': price, 'quote_received_date': '2026-11-13 10:00:00'})

    def test_setup_first_service_is_closed(self):
        self.assertEqual(self.lead.restagrup_stage_key, 'expediente')
        self.assertEqual(self.first_order.state, 'sale')

    def test_lead_knows_it_has_an_open_service(self):
        self.assertTrue(self.lead.restagrup_has_open_services)
        self.assertTrue(self.lead.restagrup_proposal_ready)

    def test_proposal_in_file_stage_only_has_the_open_service(self):
        self.assertEqual(self.lead._restagrup_proposal_searches(), self.second_search)

    def test_proposal_tab_shows_closed_choice_and_open_quotes(self):
        self.assertIn(self.first_line, self.lead.restagrup_proposal_line_ids)
        self.assertIn(self.second_line, self.lead.restagrup_proposal_line_ids)

    def test_open_line_knows_its_service_has_no_order(self):
        self.assertFalse(self.second_line.restagrup_search_order_id)
        self.assertEqual(self.first_line.restagrup_search_order_id, self.first_order)

    def test_choosing_the_open_restaurant_allows_creating_the_quote(self):
        self.assertFalse(self.lead.restagrup_quote_ready)
        self.second_line.action_toggle_chosen()
        self.assertTrue(self.lead.restagrup_quote_ready)

    def test_create_quote_makes_an_additional_order_and_opens_it(self):
        self.second_line.action_toggle_chosen()
        first_lines = self.first_order.order_line
        action = self.lead.action_create_joint_quote()
        new_order = self.second_search.sale_order_id
        self.assertTrue(new_order)
        self.assertNotEqual(new_order, self.first_order)
        self.assertEqual(action['res_id'], new_order.id)
        self.assertEqual(self.first_order.order_line, first_lines)
        self.assertEqual(self.first_order.state, 'sale')
        self.assertEqual(new_order.order_line.restagrup_search_line_id, self.second_line)
        self.assertEqual(self.lead.restagrup_stage_key, 'expediente')

    def test_sending_proposal_in_file_stage_only_sends_open_services(self):
        wizard = self.env['restagrup.lead.proposal.wizard'].create({
            'lead_id': self.lead.id, 'email_to': 'grupos@segundo.example', 'subject': 'Propuesta', 'body': 'Hola'})
        wizard._restagrup_do_send()
        self.assertTrue(self.second_search.restaurant_visible or not wizard.show_restaurants)
        self.assertEqual(self.lead.restagrup_stage_key, 'expediente')
        self.assertEqual(self.first_order.state, 'sale')

    def test_proposal_rows_offer_another_saved_menu(self):
        """Reunión 13/11 (P8): «+ Otro menú» también desde la pestaña Propuesta, solo en servicios abiertos."""
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        self.assertIn('name="action_offer_other_menu"', arch)
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Costillar', 'partner_id': self.second_line.partner_id.id, 'cost_price': 11})
        action = self.second_line.action_offer_other_menu()
        self.assertEqual(self.env['restagrup.restaurant.menu'].search(action['domain']), menu)

    def test_no_open_services_once_every_service_has_its_order(self):
        self.second_line.action_toggle_chosen()
        self.lead.action_create_joint_quote()
        self.lead.invalidate_recordset()
        self.assertFalse(self.lead.restagrup_has_open_services)
