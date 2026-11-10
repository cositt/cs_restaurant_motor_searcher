# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: pantallas y textos que pidió Conchita.

- Petición: fuera «Nuevo presupuesto»; orden 1 Pasar a presupuesto, 2 Pasar a expediente, 3 Rechazar presupuesto.
- «Añadir un servicio» en la petición y «Añadir un menú» en la ficha del restaurante.
- Lista de restaurantes con el correo.
- Ficha incompleta solo por día de cierre, responsable de grupos con móvil y cuenta bancaria; el correo para
  pedirlos es su plantilla.
- Agencias: «Origen» (canal de captación: Rubén, MA, Erika, Amelia, Instagram, Web).
- Menús: un «ojo» para ver los platos sin salir de la lista.
"""
import re

from odoo.tests.common import TransactionCase, tagged


def _header_buttons(arch):
    header = arch.split('</header>', 1)[0]
    return re.findall(r'<button[^>]*>', header)


def _index(buttons, needle):
    return next(i for i, tag in enumerate(buttons) if needle in tag)


@tagged('post_install', '-at_install')
class TestRonda0911Ui(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead_arch = cls.env['crm.lead'].get_view(view_type='form')['arch']
        cls.partner_arch = cls.env['res.partner'].get_view(
            cls.env.ref('base.view_partner_form').id, 'form')['arch']

    # --- botones de la petición ---

    def test_new_quote_button_is_gone(self):
        tag = next(t for t in _header_buttons(self.lead_arch) if 'action_sale_quotations_new' in t)
        self.assertIn('invisible="1"', tag)

    def test_buttons_follow_her_order(self):
        buttons = _header_buttons(self.lead_arch)
        to_quote = _index(buttons, 'name="action_pass_to_quote"')
        to_file = _index(buttons, 'name="action_pass_to_file"')
        reject = _index(buttons, 'Rechazar presupuesto')
        self.assertLess(to_quote, to_file)
        self.assertLess(to_file, reject)

    # --- textos de las listas ---

    def test_services_list_says_add_a_service(self):
        services = self.lead_arch.split('name="restagrup_events"', 1)[1].split('</page>', 1)[0]
        self.assertIn('Añadir un servicio', services)

    def test_restaurant_menus_say_add_a_menu(self):
        menus = self.partner_arch.split('name="restaurant_menu_catalog"', 1)[1].split('</page>', 1)[0]
        self.assertIn('Añadir un menú', menus)

    def test_restaurant_list_shows_the_email(self):
        arch = self.env['res.partner'].get_view(
            self.env.ref('restagrup_restaurants.view_partner_restaurant_list').id, 'list')['arch']
        self.assertIn('name="email"', arch)

    # --- ficha incompleta y correo para pedir los datos ---

    def test_incomplete_only_for_closing_day_manager_and_bank(self):
        partner = self.env['res.partner'].create({
            'name': 'Casa completa', 'is_restaurant': True, 'restaurant_closed_weekday': 'tue',
            'restaurant_group_manager': 'Manuel', 'restaurant_group_mobile': '600000000',
            'restaurant_iban': 'ES9121000418450200051332'})
        self.assertFalse(partner.restaurant_is_incomplete, 'Aforo e idioma ya no cuentan.')

    def test_missing_bank_still_makes_it_incomplete(self):
        partner = self.env['res.partner'].create({
            'name': 'Casa sin banco', 'is_restaurant': True, 'restaurant_closed_weekday': 'tue',
            'restaurant_group_manager': 'Manuel', 'restaurant_group_mobile': '600000000'})
        self.assertTrue(partner.restaurant_is_incomplete)

    def test_data_request_uses_her_text(self):
        partner = self.env['res.partner'].create({
            'name': 'Mesón Pide Datos', 'is_restaurant': True, 'email': 'pide@example.com'})
        lead = self.env['crm.lead'].create({'name': 'Grupo datos'})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 20})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': partner.name, 'partner_id': partner.id})
        _subject, body = line._data_request_content('Conchita')
        self.assertIn('Para poder contar con vosotros', body)
        self.assertIn('Día de cierre', body)
        self.assertIn('Responsable de reservas de grupos y su móvil', body)
        self.assertIn('Cuenta bancaria para el prepago en caso de confirmación', body)
        self.assertIn('¡Muchas gracias por vuestra colaboración!', body)

    # --- origen de la agencia ---

    def test_agency_origin_channels(self):
        names = set(self.env['restagrup.agency.origin'].search([]).mapped('name'))
        self.assertTrue({'Rubén', 'MA', 'Erika', 'Amelia', 'Instagram', 'Web'} <= names)

    def test_agency_form_has_the_origin(self):
        self.assertIn('name="restagrup_origin_id"', self.partner_arch)

    # --- ver los platos de un menú ---

    def test_menu_eye_opens_the_dishes(self):
        partner = self.env['res.partner'].create({'name': 'Casa Ojo', 'is_restaurant': True})
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú grupos', 'partner_id': partner.id, 'sale_price': 20.0,
            'description': 'Primero: gazpacho\nSegundo: pollo'})
        action = menu.action_preview_dishes()
        self.assertEqual(action['res_model'], 'restagrup.restaurant.menu')
        self.assertEqual(action['res_id'], menu.id)
        self.assertEqual(action['target'], 'new')
        self.assertIn('gazpacho', menu.display_text)

    def test_menu_lists_have_the_eye(self):
        pick = self.env['restagrup.restaurant.menu'].get_view(
            self.env.ref('restagrup_restaurants.view_restaurant_menu_pick_list').id, 'list')['arch']
        self.assertIn('action_preview_dishes', pick)
        menus = self.partner_arch.split('name="restaurant_menu_catalog"', 1)[1].split('</page>', 1)[0]
        self.assertIn('action_preview_dishes', menus)

    # --- ficha de agencia sencilla, como su CRM ---

    def test_agencies_open_a_simple_form(self):
        action = self.env['res.partner'].restagrup_action_agencies()
        form_view = dict((mode, view) for view, mode in action['views'])['form']
        self.assertEqual(form_view, self.env.ref('restagrup_service_orders.view_partner_agency_form').id)
        arch = self.env['res.partner'].get_view(form_view, 'form')['arch']
        for needle in ('Datos de facturación', 'Datos adicionales', 'name="vat"', 'name="restagrup_origin_id"',
                       'name="agency_payment_mode"', 'name="child_ids"'):
            self.assertIn(needle, arch)
        for noise in ('name="property_payment_term_id"', 'name="category_id"', 'name="user_id"'):
            self.assertNotIn(noise, arch)
