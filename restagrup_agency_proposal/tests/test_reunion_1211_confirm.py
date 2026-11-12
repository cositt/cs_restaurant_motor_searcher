# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'
WIZARD = 'restagrup.send.wizard'


@tagged('post_install', '-at_install')
class TestReviewConfirmations(TransactionCase):
    """Reunión 12/11 (7.6): las confirmaciones al restaurante y a la agencia también pasan por «Revisar y enviar»;
    con varios restaurantes, una ventana detrás de otra. (3.7/3.8) Se elige a quién va entre sus contactos."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        cls.agency = Partner.create({'name': 'Viajes 1211', 'is_company': True, 'email': 'grupos@v1211.example'})
        cls.guide = Partner.create({'name': 'Marta', 'parent_id': cls.agency.id, 'email': 'marta@v1211.example'})
        cls.first = Partner.create({'name': 'Casa Uno', 'is_restaurant': True, 'is_company': True,
                                    'email': 'uno@example.com', 'city': 'Madrid'})
        cls.second = Partner.create({'name': 'Casa Dos', 'is_restaurant': True, 'is_company': True,
                                     'email': 'dos@example.com', 'city': 'Madrid'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio 1211', 'partner_id': cls.agency.id})
        for day, restaurant in (('2026-12-15', cls.first), ('2026-12-16', cls.second)):
            event = cls.env['restagrup.lead.event'].create({
                'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': day, 'event_time': 13.5,
                'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
            search = cls.env['restagrup.restaurant.search'].create({
                'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 30})
            line = cls.env[LINE].create({
                'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
                'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 15.0,
                'quote_received_date': '2026-11-09 10:00:00'})
            line.action_toggle_chosen()
        cls.lead.action_pass_to_file()
        cls.orders = cls.lead._restagrup_live_orders()
        cls.sheets = cls.orders.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel').sorted('id')

    def _wizard(self, action):
        self.assertEqual(action['res_model'], WIZARD)
        return self.env[WIZARD].browse(action['res_id'])

    def _emails(self, records):
        return records.message_ids.filtered(lambda m: m.message_type == 'email')

    def test_restaurant_confirmation_opens_review_with_the_pdf(self):
        sheet = self.sheets[:1]
        wizard = self._wizard(sheet.action_send_confirmation_restaurant())
        self.assertFalse(self._emails(sheet), 'abrir la ventana no envía')
        self.assertTrue(any(a.name.startswith('Confirmacion-Restaurante') for a in wizard.attachment_ids))
        self.assertEqual(wizard.recipient_ids, sheet.partner_id)
        wizard.body = wizard.body + '\nLlegan 10 minutos antes.'
        wizard.action_send()
        message = self._emails(sheet)
        self.assertEqual(len(message), 1)
        self.assertIn('Llegan 10 minutos antes.', message.body)
        self.assertTrue(any(a.name.startswith('Confirmacion-Restaurante') for a in message.attachment_ids))
        self.assertTrue(any('Confirmación de reserva enviada' in (m.body or '') for m in self.lead.message_ids))

    def test_all_restaurants_one_window_after_another(self):
        self.assertEqual(len(self.sheets), 2)
        first = self._wizard(self.lead.action_send_restaurant_confirmations())
        second = self._wizard(first.action_send())
        self.assertNotEqual(first, second)
        self.assertEqual(second.recipient_ids, self.sheets[1].partner_id)
        result = second.action_send()
        self.assertNotEqual(result.get('res_model'), WIZARD)
        for sheet in self.sheets:
            self.assertEqual(len(self._emails(sheet)), 1)

    def test_chain_survives_the_firewall_warning(self):
        issue = [{'check': self.env['restagrup.firewall.check'].new({'mode': 'warn'}), 'message': 'Falta algo'}]
        with patch.object(type(self.env['purchase.order']), '_restagrup_firewall_issues', return_value=issue):
            action = self.lead.with_context(restagrup_skip_firewall=False).action_send_restaurant_confirmations()
        self.assertEqual(action['res_model'], 'restagrup.firewall.wizard')
        firewall = self.env['restagrup.firewall.wizard'].browse(action['res_id'])
        self.assertEqual(json.loads(firewall.send_chain), self.sheets[1:].ids)
        first = self._wizard(firewall.action_continue())
        second = self._wizard(first.action_send())
        self.assertEqual(second.recipient_ids, self.sheets[1].partner_id)

    def test_agency_confirmation_lets_choose_agency_contacts(self):
        wizard = self._wizard(self.lead.action_send_agency_confirmation())
        self.assertEqual(wizard.candidate_ids, self.agency | self.guide)
        self.assertEqual(wizard.recipient_ids, self.agency)
        self.assertTrue(any(a.name.startswith('Confirmacion-Agencia') for a in wizard.attachment_ids))
        wizard.recipient_ids = self.agency | self.guide
        wizard.action_send()
        message = self._emails(self.orders)[:1]
        self.assertIn('marta@v1211.example', message.outgoing_email_to)
        self.assertIn('grupos@v1211.example', message.outgoing_email_to)
        self.assertTrue(any(a.name.startswith('Confirmacion-Agencia') for a in message.attachment_ids))


@tagged('post_install', '-at_install')
class TestAgencyConfirmationFromQuote(TransactionCase):
    """Reunión 12/11 (7.3/8.4): en Presupuesto se puede enviar la confirmación a la agencia aunque el restaurante
    aún no lo haya confirmado (tenemos sus menús de la ficha). No cambia de fase ni confirma el pedido."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        cls.agency = Partner.create({'name': 'Viajes Presupuesto', 'is_company': True, 'email': 'pre@v.example'})
        restaurant = Partner.create({'name': 'Casa Catálogo', 'is_restaurant': True, 'is_company': True,
                                     'email': 'cat@example.com', 'city': 'Madrid'})
        menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú grupos 2026', 'partner_id': restaurant.id, 'cost_price': 20.0})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo en presupuesto', 'partner_id': cls.agency.id})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 25, 'event_date': '2026-12-20', 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 25})
        cls.line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'menu_id': menu.id})
        cls.line.action_quote_from_catalog()  # precio de su ficha, disponibilidad sin confirmar
        cls.line.action_toggle_chosen()
        cls.lead._restagrup_advance_to('presupuesto')

    def test_agency_confirmation_from_quote_stage_without_restaurant_ok(self):
        self.assertTrue(self.line.quote_availability_pending)
        action = self.lead.action_send_agency_confirmation()
        self.assertEqual(action['res_model'], WIZARD)
        self.env[WIZARD].browse(action['res_id']).action_send()
        order = self.lead._restagrup_live_orders()
        self.assertTrue(order.message_ids.filtered(
            lambda m: m.message_type == 'email' and m.outgoing_email_to == 'pre@v.example'))
        self.assertEqual(self.lead.restagrup_stage_key, 'presupuesto', 'no cambia de fase')
        self.assertIn(order.state, ('draft', 'sent'), 'no confirma el pedido')

    def test_button_is_visible_in_quote_stage(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        button = arch.split('name="action_send_agency_confirmation"', 1)[1].split('/>', 1)[0]
        self.assertIn('presupuesto', button)
