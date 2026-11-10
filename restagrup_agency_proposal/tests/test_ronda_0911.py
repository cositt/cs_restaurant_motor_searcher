# -*- coding: utf-8 -*-
"""Ronda de ajustes del 09/11/2026 (Conchita y Rubén probando en producción): los fallos.

1. Borrar o cancelar una petición cancela también su pedido (no se queda en «Pagos pendientes»).
2. Dirección pegada entera en «Calle»: se separan calle, código postal y ciudad (si no, el buscador no lo ve).
3. Descartar el restaurante elegido le quita la elección; con su presupuesto se puede recuperar sin pedirlo otra vez.
4. Si se ha elegido aquí antes de mandar el enlace, la agencia no podría elegir: el envío deja que elija ella.
5. «Pasar a expediente» exige el presupuesto de venta: si está todo elegido lo crea y lo confirma.
6. La confirmación al restaurante sale por correo, con su PDF, en el hilo de la hoja (y queda nota en el grupo).
7. El PDF de la propuesta lleva fecha, hora, tipo de servicio, agencia y número de documento.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRonda0911(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://demo.example.com')
        cls.agency = cls.env['res.partner'].create({
            'name': 'Sol y Nubes', 'is_company': True, 'email': 'grupos@solynubes.example', 'phone': '600111222'})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Conchita Prueba', 'parent_id': cls.agency.id, 'email': 'conchita@solynubes.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Los Arcos Test', 'is_restaurant': True, 'is_company': True,
            'email': 'arcos@example.com', 'city': 'Sevilla'})

    def _lead(self, name='Ayuntamiento'):
        lead = self.env['crm.lead'].create({'name': name, 'partner_id': self.contact.id})
        event = self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'pax': 50, 'event_date': '2026-12-15', 'event_time': 13.5,
            'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id,
        })
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 50})
        line = self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 14.0,
            'quote_received_date': '2026-11-09 11:50:00',
        })
        return lead, search, line

    def _confirmed_order(self):
        lead, search, line = self._lead()
        line.action_toggle_chosen()
        lead.action_create_joint_quote()
        order = search.sale_order_id
        order.action_confirm()
        return lead, order

    # --- 1. cancelar la petición cancela su pedido ---

    def test_deleting_a_request_cancels_its_confirmed_order(self):
        lead, order = self._confirmed_order()
        self.assertEqual(order.state, 'sale')
        lead.unlink()
        self.assertEqual(order.state, 'cancel')

    def test_cancelling_a_request_cancels_its_order_and_restaurant_sheets(self):
        lead, order = self._confirmed_order()
        sheets = order.sudo().restaurant_po_ids
        self.assertTrue(sheets)
        lead.action_set_lost()
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(set(sheets.mapped('state')), {'cancel'})

    def test_a_paid_order_is_not_cancelled_silently(self):
        lead, order = self._confirmed_order()
        order.restagrup_paid = True
        with self.assertRaises(UserError):
            lead.action_set_lost()
        self.assertEqual(order.state, 'sale')

    # --- 2. dirección pegada entera ---

    def test_pasted_address_is_split_into_street_zip_and_city(self):
        partner = self.env['res.partner'].create({
            'name': 'Restaurante El 3 de Oro Test', 'is_restaurant': True,
            'street': 'C. Sta. María la Blanca, 34, Casco Antiguo, 41001 Sevilla'})
        self.assertEqual(partner.street, 'C. Sta. María la Blanca, 34, Casco Antiguo')
        self.assertEqual(partner.zip, '41001')
        self.assertEqual(partner.city, 'Sevilla')
        self.assertEqual(partner.country_id, self.env.ref('base.es'))

    def test_address_already_split_is_left_alone(self):
        partner = self.env['res.partner'].create({
            'name': 'Casa con ciudad', 'street': 'Calle Sierpes 33, 41004 Sevilla', 'city': 'Dos Hermanas'})
        self.assertEqual(partner.city, 'Dos Hermanas')
        self.assertEqual(partner.street, 'Calle Sierpes 33, 41004 Sevilla')

    def test_pasted_address_on_edit_is_split_too(self):
        partner = self.env['res.partner'].create({'name': 'Editado', 'is_restaurant': True})
        partner.write({'street': 'Calle Larios 5, 29005 Málaga'})
        self.assertEqual((partner.street, partner.zip, partner.city), ('Calle Larios 5', '29005', 'Málaga'))

    # --- 3. descartar y volver a elegir ---

    def test_discarding_the_chosen_restaurant_removes_the_choice(self):
        _lead, search, line = self._lead()
        line.action_toggle_chosen()
        line.action_mark_descartado()
        self.assertFalse(search.chosen_line_id)

    def test_a_discarded_restaurant_with_its_quote_can_be_chosen_again(self):
        _lead, search, line = self._lead()
        line.action_mark_descartado()
        line.action_toggle_chosen()
        self.assertEqual(search.chosen_line_id, line)
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')
        self.assertEqual(line.quote_price_pp, 14.0)

    def test_recover_brings_back_a_discarded_quote(self):
        _lead, _search, line = self._lead()
        line.action_mark_descartado()
        line.action_recover_quote()
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')

    def test_a_discarded_restaurant_without_quote_still_needs_one(self):
        _lead, search, line = self._lead()
        line.write({'quote_price_pp': 0.0, 'quote_received_date': False})
        line.action_mark_descartado()
        with self.assertRaises(UserError):
            line.action_toggle_chosen()
        self.assertFalse(search.chosen_line_id)

    def test_create_quote_with_a_chosen_line_asked_again_opens_the_confirmation(self):
        """Lo que le pasó a Conchita: elegido, y luego se volvió a pedir presupuesto («Solicitado» con precio)."""
        lead, search, line = self._lead()
        line.action_toggle_chosen()
        line.etiqueta = 'solicitado'
        action = lead.action_create_joint_quote()
        self.assertEqual(action.get('res_model'), LINE)
        self.assertEqual(action.get('res_id'), line.id)
        self.assertFalse(search.sale_order_id)

    # --- 4. elegido aquí antes de mandar el enlace ---

    def test_proposal_wizard_warns_when_we_already_chose(self):
        lead, _search, line = self._lead()
        line.action_toggle_chosen()
        wizard = self.env['restagrup.lead.proposal.wizard'].create({'lead_id': lead.id})
        self.assertIn(self.restaurant.name, wizard.chosen_warning or '')
        self.assertTrue(wizard.let_agency_choose)

    def test_sending_with_the_link_lets_the_agency_choose(self):
        lead, search, line = self._lead()
        line.action_toggle_chosen()
        wizard = self.env['restagrup.lead.proposal.wizard'].create({'lead_id': lead.id, 'email_to': 'grupos@solynubes.example'})
        wizard._restagrup_do_send()
        self.assertFalse(search.chosen_line_id, 'La agencia elige desde el enlace.')

    def test_sending_keeping_our_choice(self):
        lead, search, line = self._lead()
        line.action_toggle_chosen()
        wizard = self.env['restagrup.lead.proposal.wizard'].create({'lead_id': lead.id, 'let_agency_choose': False, 'email_to': 'grupos@solynubes.example'})
        wizard._restagrup_do_send()
        self.assertEqual(search.chosen_line_id, line)

    # --- 5. pasar a expediente exige el presupuesto de venta ---

    def test_pass_to_file_without_a_chosen_restaurant_is_refused(self):
        lead, _search, _line = self._lead()
        with self.assertRaises(UserError):
            lead.action_pass_to_file()
        self.assertNotEqual(lead.restagrup_stage_key, 'expediente')

    def test_pass_to_file_creates_and_confirms_the_order(self):
        lead, search, line = self._lead()
        line.action_toggle_chosen()
        lead.action_pass_to_file()
        self.assertEqual(lead.restagrup_stage_key, 'expediente')
        self.assertEqual(search.sale_order_id.state, 'sale')
        self.assertTrue(search.sale_order_id.sudo().restaurant_po_ids)

    def test_pass_to_file_confirms_an_existing_draft_order(self):
        lead, search, line = self._lead()
        line.action_toggle_chosen()
        lead.action_create_joint_quote()
        lead.action_pass_to_file()
        self.assertEqual(search.sale_order_id.state, 'sale')
        self.assertEqual(lead.restagrup_stage_key, 'expediente')

    # --- 6. confirmación al restaurante por correo ---

    def test_restaurant_confirmation_goes_by_email_in_the_sheet_thread(self):
        lead, order = self._confirmed_order()
        sheet = order.sudo().restaurant_po_ids[:1]
        sheet.action_send_confirmation_restaurant()
        message = sheet.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        self.assertTrue(message)
        self.assertEqual(message.outgoing_email_to, 'arcos@example.com')
        self.assertTrue(any(a.name.startswith('Confirmacion-Restaurante') for a in message.attachment_ids))
        self.assertTrue(any('Confirmación de reserva enviada' in (m.body or '') for m in lead.message_ids))

    # --- 7. PDF de la propuesta con los datos del servicio ---

    def test_proposal_pdf_has_date_time_service_and_agency(self):
        lead, search, _line = self._lead()
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_agency_proposal.report_client_comparison', search.ids)
        html = html.decode()
        for text in ('15/12/2026', '13:30', 'Comida', 'Sol y Nubes', lead.restagrup_doc_number, '50 personas'):
            self.assertIn(text, html)
