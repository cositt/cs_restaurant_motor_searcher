# -*- coding: utf-8 -*-
"""Presupuesto de venta al gusto de Restagrup (ticket de Conchita 2026-11-04): numerado con el nº de la
petición, válido hasta el día del servicio, sin «Mostrar margen», precio por persona sin dividir y PDF
con su formato (cabecera del grupo, un bloque por servicio con el menú y el precio neto por persona)."""
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQuoteFormat(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({
            'name': 'Agencia Clandestina', 'is_company': True, 'phone': '+34 600 000 000',
            'email': 'reservas@clandestina.example.com'})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Erika Zarandona', 'parent_id': cls.agency.id, 'email': 'erika@clandestina.example.com',
            'lang': 'es_ES'})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Colegio Teresianas', 'partner_id': cls.contact.id})
        cls.lunch = cls.env.ref('restagrup_core.event_type_lunch')
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante La Fría', 'is_restaurant': True, 'street': 'C. Playa del Chanquete, 91',
            'city': 'Málaga'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'MENÚ 1 2026', 'partner_id': cls.restaurant.id, 'cost_price': 19.0,
            'description': 'CAVA DE BIENVENIDA\nESPETOS DE SARDINAS\nINCLUIDO POSTRE'})

    def _search(self, service_date=date(2027, 2, 1), pax=30, city='Málaga'):
        event = self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': city, 'pax': pax, 'event_date': service_date,
            'event_time': 13.5, 'event_type_id': self.lunch.id})
        return self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'event_id': event.id, 'city': city, 'min_capacity': pax})

    def _order(self, search=None, price_pp=19.0):
        search = search or self._search()
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido',
            'quote_price_pp': price_pp, 'menu_id': self.menu.id})
        line.action_toggle_chosen()
        search.action_create_sale_order()
        return search.sale_order_id

    def _petition_number(self):
        return 'PET%s-%s' % (self.lead.create_date.strftime('%Y%m'), self.lead.restagrup_doc_seq)

    # --- precio por persona: nunca 0,76 € ---

    def test_sale_line_keeps_the_price_per_person(self):
        line = self._order(price_pp=19.0).order_line
        self.assertEqual(line.product_uom_qty, 30)
        self.assertAlmostEqual(line.restagrup_unit_cost, 19.0)
        self.assertAlmostEqual(line.price_unit, 22.8, msg='19 € + 20 % de margen, por persona')

    # --- número = nº de petición ---

    def test_order_is_numbered_with_the_petition_number(self):
        self.assertEqual(self._order().name, self._petition_number())

    def test_additional_order_of_the_same_group_gets_a_suffix(self):
        first = self._order()
        first.action_confirm()
        second = self._order(search=self._search(service_date=date(2027, 2, 2), city='Sevilla'))
        self.assertNotEqual(second, first)
        self.assertEqual(second.name, '%s-2' % self._petition_number())

    def test_order_without_group_keeps_the_standard_sequence(self):
        order = self.env['sale.order'].create({'partner_id': self.agency.id})
        self.assertFalse(order.name.startswith('PET'))

    # --- vencimiento = día del servicio ---

    def test_quote_is_valid_until_the_service_day(self):
        self.assertEqual(self._order(search=self._search(service_date=date(2027, 2, 1))).validity_date,
                         date(2027, 2, 1))

    def test_validity_follows_the_first_service(self):
        order = self._order(search=self._search(service_date=date(2027, 3, 10)))
        self._order(search=self._search(service_date=date(2027, 3, 5), city='Sevilla'))
        self.assertEqual(order.validity_date, date(2027, 3, 5), 'mismo presupuesto del grupo: el primer servicio')

    # --- sin «Mostrar margen» ---

    def test_show_margin_switch_is_hidden(self):
        arch = self.env['sale.order'].get_view(view_type='form')['arch']
        for node in arch.split('<field name="restagrup_show_margin"')[1:]:
            self.assertIn('invisible="1"', node.split('/>')[0])

    # --- PDF con su formato ---

    def _pdf_html(self, order):
        html, _ = self.env['ir.actions.report']._render_qweb_html('sale.report_saleorder', order.ids)
        return html.decode()

    def test_pdf_has_the_group_header(self):
        order = self._order()
        html = self._pdf_html(order)
        for text in ('PRESUPUESTO', self._petition_number(), 'Colegio Teresianas', 'Agencia Clandestina',
                     '+34 600 000 000', 'Erika Zarandona'):
            self.assertIn(text, html)

    def test_pdf_has_one_block_per_service_with_menu_and_net_price(self):
        html = self._pdf_html(self._order())
        for text in ('1º Servicio', 'Málaga', '01/02/2027', 'PAX: 30', 'Restaurante La Fría',
                     'C. Playa del Chanquete, 91', self.lunch.name, '13:30', 'MENÚ 1 2026', 'ESPETOS DE SARDINAS',
                     'PRECIO NETO', '22,80'):
            self.assertIn(text, html)

    def test_pdf_has_the_guest_number_note(self):
        html = self._pdf_html(self._order())
        self.assertIn('sujeto a disponibilidad', html)

    # --- respuesta de Conchita 2026-11-09: 72 h para cambiar comensales y gastos de gestión ---

    def test_pdf_guest_note_gives_72_hours_and_management_fees(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.final_pax_hours')]).unlink()
        text = ' '.join(self._pdf_html(self._order()).split())
        self.assertIn('72 horas antes del servicio', text)
        self.assertIn('100 % de los gastos de gestión', text)
        self.assertNotIn('laborables', text)

    def test_pdf_guest_note_follows_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.final_pax_hours', '24')
        text = ' '.join(self._pdf_html(self._order()).split())
        self.assertIn('24 horas antes del servicio', text)

    def test_pdf_contact_row_shows_the_contact_person_phone(self):
        self.contact.phone = '611 222 333'
        html = self._pdf_html(self._order())
        for text in ('Agencia Clandestina', '+34 600 000 000', 'Erika Zarandona', '611 222 333'):
            self.assertIn(text, html)

    def test_pdf_does_not_show_the_group_total_as_unit_price(self):
        html = self._pdf_html(self._order())
        self.assertNotIn('0,76', html)
