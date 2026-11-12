# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11: la factura a la agencia como la de su CRM.

Antes salía la factura estándar con el menú entero en la descripción y sin los datos fiscales. Ahora:
- Una línea por servicio: fecha, «MENU Comida en "Restaurante"», precio del menú, PAX y total (sin platos).
- Arriba la razón social de Restagrup con su dirección y NIF; los datos de la agencia; nº de factura, fecha,
  expediente y grupo. Abajo subtotal, IVA y total, y un pie con los datos fiscales.
"""
import re

from odoo.tests.common import TransactionCase, tagged

TEMPLATE = 'restagrup_agency_proposal.report_invoice_restagrup'


def _text(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.decode() if isinstance(html, bytes) else html))


@tagged('post_install', '-at_install')
class TestRonda1111Invoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        company.write({'vat': 'ESB92402312', 'street': 'C/ Francisco Guillón, nº 17', 'zip': '29017',
                       'city': 'Málaga', 'email': 'administracion@restagrup.example'})
        cls.env['ir.config_parameter'].sudo().set_param(
            'restagrup.legal_name', 'Inversiones y Promociones Aracil, SL')
        tax = cls.env['account.tax'].create({
            'name': 'IVA 10% incl. test', 'amount': 10, 'amount_type': 'percent', 'price_include_override':
            'tax_included', 'type_tax_use': 'sale', 'company_id': company.id})
        cls.agency = cls.env['res.partner'].create({
            'name': 'Europe Incoming Test', 'is_company': True, 'street': '11-12 Turnham Green Terrace Mews',
            'city': 'London', 'vat': 'GB125469114', 'email': 'eu@incoming.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'VERONA 63 Test', 'is_restaurant': True, 'email': 'v@verona.example', 'city': 'Madrid'})
        product = cls.env['product.template'].create({
            'name': 'Servicio de restaurante (grupo)', 'type': 'service', 'sale_ok': True, 'invoice_policy': 'order',
            'restaurant_id': cls.restaurant.id, 'taxes_id': [(6, 0, tax.ids)]}).product_variant_id
        dinner = cls.env.ref('restagrup_core.event_type_dinner', raise_if_not_found=False) or \
            cls.env['restagrup.event.type'].create({'name': 'Cena'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.agency.id, 'client_order_ref': 'E260300098',
            'order_line': [(0, 0, {
                'product_id': product.id, 'product_uom_qty': 62, 'price_unit': 21.60,
                'name': 'Servicio de restaurante (grupo)\nMenú\nEntrante:\n- Espaguetis a la Napolitana',
                'service_date': '2026-03-28', 'service_event_type_id': dinner.id,
                'restaurant_id': cls.restaurant.id})]})
        cls.order.action_confirm()
        cls.invoice = cls.order._create_invoices()
        cls.invoice.action_post()

    def _html(self):
        return _text(self.env['ir.actions.report']._render_qweb_html('account.report_invoice', self.invoice.ids)[0])

    def test_customer_invoices_use_our_template(self):
        self.assertEqual(self.invoice._get_name_invoice_report(), TEMPLATE)

    def test_invoice_line_is_one_short_line_per_service(self):
        self.assertEqual(self.invoice.invoice_line_ids.name, 'MENU Cena en "VERONA 63 Test"')

    def test_header_has_our_fiscal_data_and_the_agency(self):
        html = self._html()
        for text in ('Inversiones y Promociones Aracil, SL', 'C/ Francisco Guillón, nº 17', '29017', 'Málaga',
                     'B92402312', 'Datos agencia', 'Europe Incoming Test', 'GB125469114',
                     self.invoice.name, self.order.name, 'E260300098'):
            self.assertIn(text, html)

    def test_lines_show_date_menu_price_pax_and_total(self):
        html = self._html()
        for text in ('Fecha servicio', 'Precio Menú', 'PAX', '28/03/2026', 'MENU Cena en', '21,60', '62',
                     '1.339,20'):
            self.assertIn(text, html)
        self.assertNotIn('Espaguetis', html)

    def test_totals_break_down_the_vat(self):
        html = self._html()
        self.assertIn('Subtotal', html)
        self.assertIn('1.217,45', html)  # 1.339,20 / 1,10
        self.assertIn('121,75', html)
        self.assertIn('Total', html)
