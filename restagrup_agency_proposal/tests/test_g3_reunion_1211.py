# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestG3Reunion1211(TransactionCase):
    """Reunión 12/11, bloque G3: 6.6 servicios en grande bajo el documento («Serv. 1: CIUDAD | dd/mm/aa hh:mm»);
    7.8/8.3 las notas del grupo son internas y las de cada servicio van a la agencia y al restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        cls.agency = Partner.create({'name': 'Agencia G3', 'is_company': True, 'email': 'agencia-g3@example.com'})
        cls.restaurant = Partner.create({'name': 'Casa G3', 'is_restaurant': True, 'is_company': True,
                                         'email': 'casa-g3@example.com', 'city': 'Madrid'})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Colegio G3', 'partner_id': cls.agency.id, 'description': '<p>Cliente difícil, ojo</p>'})
        lunch = cls.env.ref('restagrup_core.event_type_lunch')
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': '2027-10-23', 'event_time': 13.0,
            'event_type_id': lunch.id, 'sequence': 10, 'notes': '2 celiacos. Guía: Marta 600 000 000'})
        cls.event2 = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Toledo', 'pax': 28, 'event_date': '2027-10-24', 'event_time': 21.0,
            'event_type_id': cls.env.ref('restagrup_core.event_type_dinner').id, 'sequence': 20})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Madrid', 'min_capacity': 30})
        cls.line = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'email': cls.restaurant.email, 'etiqueta': 'presupuesto_recibido',
            'quote_price_pp': 15.0, 'quote_received_date': '2026-11-09 10:00:00'})

    # --- 6.6 ---
    def test_services_headline_like_their_crm(self):
        headline = self.lead.restagrup_services_headline
        self.assertIn('Serv. 1: MADRID | 23/10/27 13:00 · 30 pax', headline)
        self.assertIn('Serv. 2: TOLEDO | 24/10/27 21:00 · 28 pax', headline)

    def test_no_services_no_headline(self):
        lead = self.env['crm.lead'].create({'name': 'Sin servicios'})
        self.assertFalse(lead.restagrup_services_headline)

    def test_headline_is_shown_in_the_form(self):
        arch = self.env['crm.lead'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('restagrup_services_headline', arch)

    # --- 7.8 / 8.3 ---
    def test_lead_notes_tab_is_internal(self):
        arch = self.env['crm.lead'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('string="Notas internas"', arch)

    def test_service_notes_are_labelled_for_third_parties(self):
        field = self.env['restagrup.lead.event']._fields['notes']
        self.assertEqual(field.string, 'Notas para agencia y restaurante')

    def test_service_notes_go_in_the_quote_request(self):
        values = self.line._mail_values('Ana')
        self.assertIn('2 celiacos', values['notas'])

    def test_service_notes_and_not_internal_ones_go_to_the_restaurant(self):
        self.line.action_toggle_chosen()
        self.lead.action_pass_to_file()
        order = self.lead._restagrup_live_orders()
        sheet = order.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')[:1]
        text = sheet._restagrup_service_lines_text()
        self.assertIn('2 celiacos. Guía: Marta 600 000 000', text)
        self.assertNotIn('Cliente difícil', text)
        info = order.order_line.filtered('restaurant_id')[:1]._restagrup_service_info()
        self.assertEqual(info['notes'], '2 celiacos. Guía: Marta 600 000 000')
        html = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_agency_proposal.report_booking_confirmation', order.ids)[0].decode()
        self.assertIn('2 celiacos', html)
        self.assertNotIn('Cliente difícil', html)
