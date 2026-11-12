# -*- coding: utf-8 -*-
"""Notas de Conchita tras la reunión del 05/11/2026, bloque medio:

- Ficha de agencia como la de su CRM: nombre comercial, código y forma de pago (Prepago / Crédito).
- «AV, voucher o localizador» por servicio, en los documentos y en la factura.
- Cabecera de los PDF como los suyos: agencia, teléfono, nombre, contacto y agente.
- Confirmación al restaurante con el texto de la cuenta y las 48 h.
- Beneficio arriba en el expediente (agencia, restaurantes, comisión) y aviso de variación de divisa.
- En el expediente, Propuesta y Menús solo con lo cerrado.
- Estadísticas: tiempos por presupuesto y por comercial, y media de cambios.
"""
import re
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion0511Medio(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('restagrup.default_margin_percent', '20')
        set_param('restagrup.foreign_margin_percent', '25')
        cls.env.company.country_id = cls.env.ref('base.es')
        cls.agency = cls.env['res.partner'].create({
            'name': 'Costa Viajes Ibéricos', 'is_company': True, 'phone': '91 000 00 00'})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Lucía Prieto', 'parent_id': cls.agency.id, 'phone': '600 11 22 33',
            'email': 'lucia@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Bodega Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Sevilla',
            'email': 'bodega@example.com', 'country_id': cls.env.ref('base.es').id})
        cls.product = cls.env['product.template'].create({
            'name': 'Menú bodega', 'type': 'service', 'standard_price': 30.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id
        cls.lead = cls.env['crm.lead'].create({'name': 'Senior Andalucía', 'partner_id': cls.contact.id})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.contact.id, 'opportunity_id': cls.lead.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id, 'product_uom_qty': 43, 'restagrup_gratuities': 2,
                'service_date': '2026-12-20', 'service_hour': 14.0, 'restagrup_voucher': 'AV-778/26'})],
        })
        cls.line = cls.order.order_line

    def _html(self, report, records):
        html = self.env['ir.actions.report']._render_qweb_html(report, records.ids)[0]
        return html.decode() if isinstance(html, bytes) else str(html)

    # --- ficha de agencia (punto 3) ---

    def test_agency_has_trade_name_code_and_payment_mode(self):
        self.assertEqual(self.agency.agency_payment_mode, 'prepago')
        self.agency.write({'agency_trade_name': 'CVI', 'agency_payment_mode': 'credito', 'ref': 'AGN00000042'})
        self.assertEqual(self.agency.agency_payment_mode, 'credito')

    def test_agency_form_shows_additional_data_only_for_agencies(self):
        arch = self.env['res.partner'].get_view(self.env.ref('base.view_partner_form').id, 'form')['arch']
        block = arch.split('name="agency_data"', 1)[1].split('</group>', 1)[0]
        for field in ('agency_trade_name', 'agency_payment_mode', 'ref'):
            self.assertIn('name="%s"' % field, block, field)
        tag = re.search(r'<group[^>]*name="agency_data"[^>]*>', arch).group(0)
        self.assertIn('is_restaurant', tag)

    # --- AV / voucher por servicio (punto 19) ---

    def test_voucher_goes_to_the_documents(self):
        self.assertEqual(self.line._restagrup_service_info()['voucher'], 'AV-778/26')
        self.assertIn('AV-778/26', self._html('restagrup_agency_proposal.report_booking_confirmation', self.order))
        self.assertIn('AV-778/26', self._html('restagrup_agency_proposal.report_booking_voucher', self.order))

    def test_voucher_goes_to_the_invoice(self):
        self.assertIn('AV-778/26', self.line._prepare_invoice_line()['name'])

    def test_voucher_is_editable_in_the_order_lines(self):
        arch = self.env['sale.order'].get_view(self.env.ref('sale.view_order_form').id, 'form')['arch']
        self.assertIn('name="restagrup_voucher"', arch)

    # --- cabecera de los PDF (punto 30) ---

    def test_agency_documents_header_like_their_crm(self):
        html = self._html('restagrup_agency_proposal.report_booking_confirmation', self.order)
        header = html.split('DOCUMENTO', 1)[1].split('</table>', 1)[0]
        # Etiquetas renombradas en la ronda 11/11 (TELÉFONO/NOMBRE/CONTACTO → TELÉFONO AGENCIA/CONTACTO AGENCIA)
        for label in ('GRUP. REF', 'AGENCIA', 'TELÉFONO AGENCIA', 'CONTACTO AGENCIA', 'AGENTE RESTAGRUP'):
            self.assertIn(label, header)
        self.assertIn('Costa Viajes Ibéricos', header)
        self.assertIn('91 000 00 00', header)  # teléfono de la agencia
        self.assertIn('Lucía Prieto', header)
        self.assertIn('600 11 22 33', header)  # contacto: el teléfono de la persona

    # --- cuenta del restaurante y 48 h (punto 31) ---

    def test_restaurant_confirmation_asks_for_the_account_when_missing(self):
        self.order.action_confirm()
        sheet = self.order.restaurant_po_ids[:1]
        text = sheet.restagrup_restaurant_bank_text()
        self.assertIn('Quedamos a la espera de recibir su número de cuenta', text)
        self.assertIn('48 h antes del servicio', text)
        self.assertIn('Quedamos a la espera de recibir su número de cuenta',
                      self._html('restagrup_agency_proposal.report_restaurant_confirmation', sheet))

    def test_restaurant_confirmation_shows_the_account_when_known(self):
        self.env['res.partner.bank'].create({
            'acc_number': 'ES9121000418450200051332', 'partner_id': self.restaurant.id})
        self.order.action_confirm()
        text = self.order.restaurant_po_ids[:1].restagrup_restaurant_bank_text()
        self.assertIn('48 h de antelación', text)
        self.assertIn('ES91 2100 0418 4502 0005 1332', text)
        self.assertIn('si ha cambiado', text)

    # --- beneficio arriba (punto 22) ---

    def test_file_shows_agency_restaurant_and_commission_totals(self):
        self.assertAlmostEqual(self.lead.restagrup_total_agency, self.order.amount_total)
        self.assertAlmostEqual(self.lead.restagrup_total_restaurants, 30.0 * 43)
        self.assertAlmostEqual(self.lead.restagrup_total_commission, self.order.restagrup_margin_total)
        self.assertGreater(self.lead.restagrup_total_commission, 0)
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        self.assertIn('name="restagrup_profit_bar"', arch.split('<notebook', 1)[0])

    def test_cancelled_orders_do_not_count(self):
        self.order.action_cancel()
        self.assertEqual(self.lead.restagrup_total_agency, 0.0)

    # --- variación de divisa (punto 29) ---

    def _czech_order(self):
        czk = self.env.ref('base.CZK')
        Rate = self.env['res.currency.rate']
        today = fields.Date.today()
        Rate.search([('currency_id', '=', czk.id)]).unlink()
        Rate.create({'currency_id': czk.id, 'company_id': self.env.company.id, 'name': today - timedelta(days=10),
                     'rate': 25.0})
        praga = self.env['res.partner'].create({
            'name': 'U Fleků Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Praga',
            'country_id': self.env.ref('base.cz').id, 'restaurant_currency_code': 'CZK'})
        product = self.env['product.template'].create({
            'name': 'Menú checo', 'type': 'service', 'standard_price': 20.0, 'sale_ok': True,
            'restaurant_id': praga.id}).product_variant_id
        lead = self.env['crm.lead'].create({'name': 'Grupo Praga', 'partner_id': self.contact.id})
        order = self.env['sale.order'].create({
            'partner_id': self.contact.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 40})]})
        return lead, order, czk

    def test_foreign_line_keeps_the_booking_rate(self):
        _lead, order, _czk = self._czech_order()
        line = order.order_line
        self.assertEqual(line.restagrup_fx_currency_code, 'CZK')
        self.assertAlmostEqual(line.restagrup_fx_rate, 0.04)
        self.assertAlmostEqual(line.price_unit, 25.0)  # 20 € + 25 % fuera de España

    def test_currency_variation_warns_when_profit_drops(self):
        lead, order, czk = self._czech_order()
        self.assertTrue(lead.restagrup_has_fx)
        booked = order.restagrup_margin_total
        self.assertAlmostEqual(lead.restagrup_fx_booked_profit, booked)
        self.assertAlmostEqual(lead.restagrup_fx_delta, 0.0)
        # La corona sube: 1 € = 20 CZK. El menú (500 CZK) cuesta ahora 25 € en vez de 20 €.
        self.env['res.currency.rate'].create({
            'currency_id': czk.id, 'company_id': self.env.company.id, 'name': fields.Date.today(), 'rate': 20.0})
        lead.invalidate_recordset()
        self.assertAlmostEqual(lead.restagrup_fx_delta, -5.0 * 40)
        self.assertAlmostEqual(lead.restagrup_fx_current_profit, booked - 200.0)

    def test_spanish_group_has_no_currency_warning(self):
        self.assertFalse(self.lead.restagrup_has_fx)

    # --- en el expediente, solo lo cerrado (punto 26) ---

    def test_file_tabs_show_only_what_was_closed(self):
        event = self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': 'Sevilla', 'pax': 45, 'event_date': '2026-12-20'})
        other = self.env['res.partner'].create({
            'name': 'Otro Pruebas', 'is_restaurant': True, 'is_company': True, 'city': 'Sevilla'})
        Menu = self.env['restagrup.restaurant.menu']
        chosen_menu = Menu.create({'name': 'Menú elegido', 'partner_id': self.restaurant.id, 'cost_price': 30})
        Menu.create({'name': 'Menú no elegido', 'partner_id': self.restaurant.id, 'cost_price': 40})
        Menu.create({'name': 'Menú del otro', 'partner_id': other.id, 'cost_price': 25})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 45})
        chosen = self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': 1350,
            'menu_id': chosen_menu.id})
        self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': other.name, 'partner_id': other.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 1100})
        chosen.action_toggle_chosen()
        self.assertEqual(len(self.lead.restagrup_proposal_line_ids), 2)
        self.assertEqual(len(self.lead.restagrup_candidate_menu_ids), 3)
        self.lead._restagrup_move_to('expediente')
        self.assertEqual(self.lead.restagrup_proposal_line_ids, chosen)
        self.assertEqual(self.lead.restagrup_candidate_menu_ids, chosen_menu)

    # --- estadísticas (punto 36) ---

    def test_stage_dates_are_recorded(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo estadísticas'})
        self.assertFalse(lead.restagrup_quote_date)
        lead._restagrup_move_to('presupuesto')
        self.assertTrue(lead.restagrup_quote_date)
        lead._restagrup_move_to('expediente')
        self.assertTrue(lead.restagrup_file_date)
        first = lead.restagrup_quote_date
        lead._restagrup_move_to('presupuesto')
        self.assertEqual(lead.restagrup_quote_date, first)  # la primera vez es la que cuenta

    def test_hours_to_quote_and_to_file(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo horas'})
        lead.write({'restagrup_quote_date': lead.create_date + timedelta(hours=5),
                    'restagrup_file_date': lead.create_date + timedelta(hours=30)})
        self.assertAlmostEqual(lead.restagrup_hours_to_quote, 5.0)
        self.assertAlmostEqual(lead.restagrup_hours_to_file, 30.0)

    def test_quote_changes_count_the_resent_proposals(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo cambios'})
        for _i in range(3):
            lead._restagrup_note_proposal_sent()
        self.assertEqual(lead.restagrup_proposals_sent, 3)
        self.assertEqual(lead.restagrup_quote_changes, 2)

    def test_statistics_screen_by_salesperson(self):
        action = self.env.ref('restagrup_service_orders.action_restagrup_statistics')
        self.assertEqual(action.res_model, 'crm.lead')
        self.assertIn('pivot', action.view_mode)
        pivot = self.env['crm.lead'].get_view(
            self.env.ref('restagrup_service_orders.view_restagrup_statistics_pivot').id, 'pivot')['arch']
        for field in ('user_id', 'restagrup_hours_to_quote', 'restagrup_hours_to_file', 'restagrup_quote_changes'):
            self.assertIn('name="%s"' % field, pivot)
        self.assertEqual(self.env['crm.lead']._fields['restagrup_hours_to_quote'].aggregator, 'avg')
