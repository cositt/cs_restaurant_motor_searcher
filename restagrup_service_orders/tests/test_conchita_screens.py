# -*- coding: utf-8 -*-
"""Pantallas al gusto de Restagrup (PPT de Conchita 2026-11-04): fecha con hora y año en la lista de grupos,
pestaña «Servicios» la primera, la agencia separada del grupo en el buscador y, en el presupuesto, un botón
claro para enviarlo y un aviso de cuál es el siguiente paso."""
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConchitaScreens(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia Clandestina', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Erika Zarandona', 'parent_id': cls.agency.id, 'email': 'erika@clandestina.example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Teresianas', 'partner_id': cls.contact.id})
        cls.lunch = cls.env.ref('restagrup_core.event_type_lunch')

    def _event(self, day, hour, city='Málaga'):
        return self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': city, 'pax': 30, 'event_date': day, 'event_time': hour,
            'event_type_id': self.lunch.id})

    # --- 1.1 fecha con hora y año ---

    def test_first_service_label_has_year_and_hour(self):
        self._event(date(2027, 11, 6), 21.0)
        self._event(date(2027, 11, 7), 14.5)
        self.assertEqual(self.lead.restagrup_first_service_label, '06/11/2027 21:00')

    def test_first_service_label_without_hour(self):
        self._event(date(2027, 11, 6), 0.0)
        self.assertEqual(self.lead.restagrup_first_service_label, '06/11/2027')

    def test_group_list_shows_the_label(self):
        arch = self.env.ref('restagrup_service_orders.view_crm_lead_restagrup_list').arch
        self.assertIn('restagrup_first_service_label', arch)

    # --- 1.3 pestaña Servicios la primera ---

    def test_services_tab_is_first_and_named_services(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        first_page = arch.split('<page', 1)[1].split('>', 1)[0]
        self.assertIn('name="restagrup_events"', first_page)
        self.assertIn('string="Servicios"', first_page)

    def test_event_labels_say_service(self):
        self.assertEqual(self.env['crm.lead']._fields['restagrup_event_ids'].string, 'Servicios')
        self.assertEqual(self.env['restagrup.restaurant.search']._fields['event_id'].string, 'Servicio')
        self.assertEqual(self.env['restagrup.lead.event']._fields['event_type_id'].string, 'Tipo de servicio')

    # --- 3.2 grupo y agencia separados en el buscador ---

    def test_search_shows_the_agency_apart_from_the_group(self):
        search = self.env['restagrup.restaurant.search'].create({'lead_id': self.lead.id, 'city': 'Málaga'})
        self.assertEqual(search.agency_name, 'Agencia Clandestina')
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertIn('name="agency_name"', arch)

    # --- 8.2 enviar el presupuesto y siguiente paso ---

    def _order(self):
        return self.env['sale.order'].create({'partner_id': self.contact.id, 'opportunity_id': self.lead.id})

    def test_send_button_says_send_to_agency(self):
        arch = self.env['sale.order'].get_view(view_type='form')['arch']
        primary = arch.split('id="quotation_send_primary"')[0].rsplit('<button', 1)[1] + \
            arch.split('id="quotation_send_primary"')[1].split('/>')[0]
        self.assertIn('Enviar presupuesto a la agencia', primary)

    def test_next_step_for_a_draft_quote(self):
        self.assertIn('Enviar presupuesto a la agencia', self._order().restagrup_next_step)

    def test_next_step_once_sent(self):
        order = self._order()
        order.state = 'sent'
        self.assertIn('firme', order.restagrup_next_step)

    def test_next_step_is_shown_on_the_form(self):
        arch = self.env['sale.order'].get_view(view_type='form')['arch']
        self.assertIn('name="restagrup_next_step"', arch)
