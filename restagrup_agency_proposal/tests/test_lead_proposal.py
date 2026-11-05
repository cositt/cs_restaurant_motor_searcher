# -*- coding: utf-8 -*-
"""Propuesta conjunta desde la petición (PPT de Conchita 2026-11-04, urgente 4 y diapositivas 3, 6 y 7): una sola
propuesta con todos los servicios del grupo (p. ej. Málaga + Sevilla), enviada desde la petición; la agencia elige
un restaurante por servicio en un único enlace; y un único presupuesto de venta con todos los servicios elegidos."""
import re
from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import HttpCase, TransactionCase, tagged


class ProposalSetup:

    @classmethod
    def _setup_group(cls):
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia Clandestina', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Erika Zarandona', 'parent_id': cls.agency.id, 'email': 'erika@clandestina.example.com'})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Colegio Teresianas', 'partner_id': cls.contact.id, 'email_from': cls.contact.email})
        lunch = cls.env.ref('restagrup_core.event_type_lunch')
        Event = cls.env['restagrup.lead.event']
        cls.malaga_event = Event.create({'lead_id': cls.lead.id, 'city': 'Málaga', 'pax': 30,
                                         'event_date': date(2027, 2, 1), 'event_time': 13.5,
                                         'event_type_id': lunch.id})
        cls.sevilla_event = Event.create({'lead_id': cls.lead.id, 'city': 'Sevilla', 'pax': 20,
                                          'event_date': date(2027, 2, 2), 'event_time': 14.0,
                                          'event_type_id': lunch.id})
        Search = cls.env['restagrup.restaurant.search']
        cls.malaga = Search.create({'lead_id': cls.lead.id, 'event_id': cls.malaga_event.id, 'city': 'Málaga',
                                    'min_capacity': 30})
        cls.sevilla = Search.create({'lead_id': cls.lead.id, 'event_id': cls.sevilla_event.id, 'city': 'Sevilla',
                                     'min_capacity': 20})
        cls.fria = cls._quote(cls.malaga, 'Restaurante La Fría', 19.0, 'Espetos de sardinas')
        cls.pimpi = cls._quote(cls.malaga, 'Bodega El Pimpi', 25.0, 'Porra antequerana')
        cls.telmo = cls._quote(cls.sevilla, 'Bodega San Telmo', 24.5, 'Bacalao con tomate')

    @classmethod
    def _quote(cls, search, name, price_pp, dish):
        partner = cls.env['res.partner'].create({
            'name': name, 'is_restaurant': True, 'email': '%s@example.com' % name.split()[-1].lower()})
        menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú grupos %s' % name, 'partner_id': partner.id, 'cost_price': price_pp,
            'line_ids': [(0, 0, {'course': 'principal', 'name': dish})]})
        return cls.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': name, 'partner_id': partner.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': price_pp, 'menu_id': menu.id})


@tagged('post_install', '-at_install')
class TestLeadProposal(ProposalSetup, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_group()

    def _wizard(self, **vals):
        action = self.lead.action_open_proposal_wizard()
        wizard = self.env[action['res_model']].with_context(action.get('context', {})).create(dict(
            {'lead_id': self.lead.id}, **vals))
        return wizard

    # --- enviar la propuesta desde la petición ---

    def test_wizard_defaults(self):
        wizard = self._wizard()
        self.assertEqual(wizard.email_to, 'erika@clandestina.example.com')
        self.assertIn(self.lead._restagrup_locator(), wizard.subject)

    def test_review_lists_every_service_with_its_options(self):
        text = self._wizard()._fw_review_proposal()
        for expected in ('Málaga', 'Sevilla', 'Restaurante La Fría', 'Bodega San Telmo', '22,80', '29,40'):
            self.assertIn(expected, text)

    def test_send_posts_one_mail_with_pdf_and_link(self):
        self._wizard().with_context(restagrup_skip_firewall=True).action_send()
        mails = self.lead.message_ids.filtered(lambda m: m.message_type == 'email')
        self.assertEqual(len(mails), 1)
        self.assertIn('/propuesta/%s/' % self.lead.id, mails.body)
        self.assertEqual(mails.attachment_ids.mimetype, 'application/pdf')
        self.assertEqual(self.lead.restagrup_stage_key, 'presupuesto')

    def test_hiding_restaurants_applies_to_every_service(self):
        self._wizard(show_restaurants=False).with_context(restagrup_skip_firewall=True).action_send()
        self.assertEqual((self.malaga | self.sevilla).mapped('restaurant_visible'), [False, False])

    def test_service_without_quotes_stops_the_send(self):
        self.telmo.etiqueta = 'solicitado'
        with self.assertRaisesRegex(UserError, 'Sevilla'):
            self._wizard().action_send()

    # --- un presupuesto con todos los servicios ---

    def test_joint_quote_has_every_chosen_service(self):
        self.fria.action_toggle_chosen()
        self.telmo.action_toggle_chosen()
        action = self.lead.action_create_joint_quote()
        order = self.env['sale.order'].browse(action['res_id'])
        self.assertEqual(order.order_line.restaurant_id, self.fria.partner_id | self.telmo.partner_id)
        self.assertEqual(order.name, self.lead._restagrup_locator())
        self.assertEqual((self.malaga.sale_order_id, self.sevilla.sale_order_id), (order, order))

    def test_joint_quote_needs_a_restaurant_per_service(self):
        self.fria.action_toggle_chosen()
        with self.assertRaisesRegex(UserError, 'Sevilla'):
            self.lead.action_create_joint_quote()

    # --- pestañas Propuesta y Menús en la petición ---

    def test_proposal_tab_lists_received_quotes(self):
        self.assertEqual(self.lead.restagrup_proposal_line_ids, self.fria | self.pimpi | self.telmo)

    def test_menus_tab_lists_candidate_menus(self):
        self.assertEqual(self.lead.restagrup_candidate_menu_ids, (self.fria | self.pimpi | self.telmo).menu_id)

    def test_screens(self):
        lead_form = self.env['crm.lead'].get_view(view_type='form')['arch']
        for text in ('name="action_open_proposal_wizard"', 'name="action_create_joint_quote"',
                     'name="restagrup_proposal"', 'name="restagrup_menus"'):
            self.assertIn(text, lead_form)
        search_form = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        header = search_form.split('</header>')[0]
        self.assertNotIn('Enviar comparativa al cliente', header, 'al cliente solo desde la petición')
        self.assertNotIn('Comparativa para el cliente', header)
        self.assertNotIn('string="Crear presupuesto de venta"', header)


@tagged('post_install', '-at_install')
class TestLeadProposalPortal(ProposalSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_group()
        url = cls.lead._restagrup_proposal_portal_url()
        cls.path = '/' + url.split('://', 1)[1].split('/', 1)[1]

    def test_page_shows_every_service(self):
        text = re.sub(r'<[^>]+>', ' ', self.url_open(self.path).text)
        for expected in ('Málaga', 'Sevilla', 'Restaurante La Fría', 'Bodega El Pimpi', 'Bodega San Telmo',
                         'Espetos de sardinas'):
            self.assertIn(expected, text)
        self.assertNotRegex(text, r'19[.,]00', 'nunca el coste del restaurante')

    def test_agency_chooses_one_restaurant_per_service(self):
        self.url_open('%s/elegir' % self.path, data={'search_id': self.malaga.id, 'line_id': self.pimpi.id})
        self.url_open('%s/elegir' % self.path, data={'search_id': self.sevilla.id, 'line_id': self.telmo.id})
        self.assertEqual(self.malaga.chosen_line_id, self.pimpi)
        self.assertEqual(self.sevilla.chosen_line_id, self.telmo)

    def test_wrong_token_is_not_found(self):
        self.assertEqual(self.url_open('/propuesta/%s/falso' % self.lead.id).status_code, 404)

    def test_line_of_another_service_is_ignored(self):
        self.url_open('%s/elegir' % self.path, data={'search_id': self.malaga.id, 'line_id': self.telmo.id})
        self.assertFalse(self.malaga.chosen_line_id)
