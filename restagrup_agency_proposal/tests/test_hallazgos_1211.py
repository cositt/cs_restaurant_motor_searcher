# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'
WIZARD = 'restagrup.send.wizard'


@tagged('post_install', '-at_install')
class TestHallazgos1211(TransactionCase):
    """Hallazgos de la prueba en prod del 12/11: (b) el cortafuegos acepta el email de un contacto del restaurante,
    (c) la nota de confirmación sale una sola vez en el lead, (d) la fecha no se repite en el texto al restaurante,
    (e) cancelar el pedido cancela sus hojas de servicio."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        cls.agency = Partner.create({'name': 'Viajes H1211', 'is_company': True, 'email': 'grupos@h1211.example'})
        cls.restaurant = Partner.create({'name': 'Casa H1211', 'is_restaurant': True, 'is_company': True,
                                         'email': 'casa@h1211.example', 'city': 'Madrid'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio H1211', 'partner_id': cls.agency.id})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': '2026-12-15', 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 30})
        line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 15.0,
            'quote_received_date': '2026-11-09 10:00:00'})
        line.action_toggle_chosen()
        cls.lead.action_pass_to_file()
        cls.order = cls.lead._restagrup_live_orders()
        cls.sheet = cls.order.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')

    def _lead_notes(self, text):
        return self.lead.message_ids.filtered(lambda m: text in (m.body or ''))

    # (b) ------------------------------------------------------------------------------------------------------
    def test_firewall_accepts_email_of_a_restaurant_contact(self):
        self.restaurant.email = False
        self.env['res.partner'].create({'name': 'Reservas', 'parent_id': self.restaurant.id,
                                        'email': 'reservas@h1211.example'})
        self.assertFalse(self.sheet._fw_restaurant_email())

    def test_firewall_warns_when_nobody_has_email(self):
        self.restaurant.email = False
        self.assertTrue(self.sheet._fw_restaurant_email())

    # (c) ------------------------------------------------------------------------------------------------------
    def test_agency_confirmation_note_once_on_the_lead(self):
        wizard = self.env[WIZARD].browse(self.lead.action_send_agency_confirmation()['res_id'])
        wizard.action_send()
        self.assertEqual(len(self._lead_notes('Confirmación de reserva enviada a la agencia')), 1)

    def test_restaurant_confirmation_note_once_on_the_lead(self):
        wizard = self.env[WIZARD].browse(self.sheet.action_send_confirmation_restaurant()['res_id'])
        wizard.action_send()
        self.assertEqual(len(self._lead_notes('Confirmación de reserva enviada a Casa H1211')), 1)

    # (d) ------------------------------------------------------------------------------------------------------
    def test_service_text_does_not_repeat_the_date(self):
        text = self.sheet._restagrup_service_lines_text()
        self.assertIn('15/12/2026 13:30', text)
        self.assertEqual(text.count('15/12'), 1, text)
        self.assertIn('Servicio en Casa H1211', text)

    def test_service_text_does_not_repeat_the_pax(self):
        text = self.sheet._restagrup_service_lines_text()
        self.assertEqual(text.count('pax'), 1, text)
        self.assertIn('30 pax', text)
        self.assertIn('Casa H1211 — Madrid', text)

    # (e) ------------------------------------------------------------------------------------------------------
    def test_cancelling_the_order_cancels_its_sheets(self):
        self.assertTrue(self.sheet)
        self.order._action_cancel()
        self.assertEqual(self.order.state, 'cancel')
        self.assertEqual(set(self.sheet.mapped('state')), {'cancel'})
