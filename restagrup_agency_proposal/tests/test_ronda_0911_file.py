# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: el expediente, con sus documentos a mano.

- «Enviar confirmación a la agencia»: correo con la confirmación en PDF; dice que la reserva queda confirmada y
  pide completar los datos (menú elegido, contacto del guía, intolerancias). Cuenta como una proforma más.
- Desde el propio expediente: descargar Conf. agencia, Conf. restaurante y Bono, y enviar la confirmación a los
  restaurantes, sin tener que ir al pedido.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


def _report(action):
    """Sin el diseño de documentos configurado, Odoo envuelve el informe en su asistente de diseño."""
    return action.get('context', {}).get('report_action', action)


@tagged('post_install', '-at_install')
class TestRonda0911File(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.agency = cls.env['res.partner'].create({
            'name': 'Viajes Expediente', 'is_company': True, 'email': 'grupos@expediente.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Expediente', 'is_restaurant': True, 'is_company': True,
            'email': 'casa@expediente.example', 'city': 'Sevilla'})

    def _file(self):
        lead = self.env['crm.lead'].create({'name': 'Colegio', 'partner_id': self.agency.id})
        event = self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'pax': 30, 'event_date': '2026-12-15', 'event_time': 13.5,
            'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 30})
        line = self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 15.0,
            'quote_received_date': '2026-11-09 10:00:00'})
        line.action_toggle_chosen()
        lead.action_pass_to_file()
        return lead, search.sale_order_id

    # --- confirmación a la agencia ---

    def test_agency_confirmation_goes_by_email_with_its_pdf(self):
        lead, order = self._file()
        lead.action_send_agency_confirmation()
        message = order.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        self.assertTrue(message)
        self.assertEqual(message.outgoing_email_to, 'grupos@expediente.example')
        self.assertTrue(any(a.name.startswith('Confirmacion-Agencia') for a in message.attachment_ids))
        body = message.body or ''
        self.assertIn('queda confirmada', body)
        for asked in ('menú', 'guía', 'intolerancias'):
            self.assertIn(asked, body)

    def test_agency_confirmation_counts_as_a_proforma(self):
        lead, _order = self._file()
        before = lead.restagrup_proformas_sent
        lead.action_send_agency_confirmation()
        self.assertEqual(lead.restagrup_proformas_sent, before + 1)
        self.assertTrue(any('Confirmación de reserva enviada a la agencia' in (m.body or '')
                            for m in lead.message_ids))

    def test_agency_confirmation_without_email_says_so(self):
        lead, order = self._file()
        order.partner_id.email = False
        with self.assertRaises(UserError):
            lead.action_send_agency_confirmation()

    def test_agency_confirmation_needs_the_order(self):
        lead = self.env['crm.lead'].create({'name': 'Sin pedido'})
        with self.assertRaises(UserError):
            lead.action_send_agency_confirmation()

    # --- documentos desde el expediente ---

    def test_download_agency_confirmation_from_the_file(self):
        lead, order = self._file()
        action = _report(lead.action_download_agency_confirmation())
        self.assertEqual(action['report_name'], 'restagrup_agency_proposal.report_booking_confirmation')
        self.assertEqual(action['context']['active_ids'], order.ids)

    def test_download_restaurant_confirmation_from_the_file(self):
        lead, order = self._file()
        action = _report(lead.action_download_restaurant_confirmation())
        self.assertEqual(action['report_name'], 'restagrup_agency_proposal.report_restaurant_confirmation')
        self.assertEqual(set(action['context']['active_ids']), set(order.sudo().restaurant_po_ids.ids))

    def test_voucher_needs_the_payment(self):
        lead, order = self._file()
        with self.assertRaises(UserError):
            lead.action_download_voucher()
        order.action_mark_paid()
        action = _report(lead.action_download_voucher())
        self.assertEqual(action['report_name'], 'restagrup_agency_proposal.report_booking_voucher')

    def test_send_restaurant_confirmations_from_the_file(self):
        lead, order = self._file()
        lead.action_send_restaurant_confirmations()
        sheet = order.sudo().restaurant_po_ids[:1]
        self.assertTrue(sheet.message_ids.filtered(
            lambda m: m.message_type == 'email' and m.outgoing_email_to == 'casa@expediente.example'))

    def test_file_header_has_the_document_buttons(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch'].split('</header>', 1)[0]
        for name in ('action_send_agency_confirmation', 'action_download_agency_confirmation',
                     'action_download_restaurant_confirmation', 'action_download_voucher',
                     'action_send_restaurant_confirmations'):
            self.assertIn('name="%s"' % name, arch)


@tagged('post_install', '-at_install')
class TestRonda0911PortalDishes(TransactionCase):
    """Al elegir en el enlace, la agencia puede escribir (si quiere) los platos o lo que necesite."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Portal', 'is_restaurant': True, 'email': 'portal@example.com', 'city': 'Sevilla'})
        agency = cls.env['res.partner'].create({'name': 'Agencia Portal', 'is_company': True,
                                                'email': 'a@portal.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo portal', 'partner_id': agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Sevilla', 'min_capacity': 20})
        cls.line = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 12.0,
            'quote_received_date': '2026-11-09 10:00:00'})

    def test_choosing_with_dishes_keeps_them(self):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, 'Salmorejo y presa; 2 celíacos')
        self.assertEqual(self.search.chosen_line_id, self.line)
        self.assertEqual(self.line.agency_choice_notes, 'Salmorejo y presa; 2 celíacos')
        self.assertTrue(any('2 celíacos' in (m.body or '') for m in self.lead.message_ids))

    def test_choosing_without_dishes_is_fine(self):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, '   ')
        self.assertEqual(self.search.chosen_line_id, self.line)
        self.assertFalse(self.line.agency_choice_notes)

    def test_a_foreign_line_is_ignored(self):
        self.lead._restagrup_portal_choose(self.search.id, 999999, 'x')
        self.assertFalse(self.search.chosen_line_id)

    def test_portal_form_has_the_optional_box(self):
        arch = self.env.ref('restagrup_agency_proposal.portal_lead_proposal').arch
        self.assertIn('name="dishes"', arch)

    def test_what_the_agency_wrote_goes_to_the_order_observations(self):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, 'Sin gluten para 2')
        self.lead.with_context(restagrup_skip_firewall=True).action_create_joint_quote()
        self.assertIn('Sin gluten para 2', self.search.sale_order_id.restagrup_observations or '')
