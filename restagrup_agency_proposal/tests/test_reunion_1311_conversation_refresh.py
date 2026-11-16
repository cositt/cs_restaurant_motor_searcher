# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

BUS_TYPE = 'restagrup_conversation_refresh'
LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion1311ConversationRefresh(TransactionCase):
    """Reunión 13/11 (P13): cuando entra o sale un mensaje de la conversación del grupo (en el lead, su pedido, una
    tarjeta del buscador o la hoja del restaurante), se avisa por el bus para que la pestaña Conversación se
    actualice sin F5."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        agency = Partner.create({'name': 'Viajes Bus', 'is_company': True, 'email': 'grupos@bus.example'})
        restaurant = Partner.create({'name': 'Casa Bus', 'is_restaurant': True, 'is_company': True,
                                     'email': 'casa@bus.example', 'city': 'Madrid'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Bus', 'partner_id': agency.id})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': '2026-12-15', 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 30})
        cls.line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 15.0, 'quote_received_date': '2026-11-09 10:00:00'})
        cls.other_lead = cls.env['crm.lead'].create({'name': 'Otro grupo'})

    def _post_and_capture(self, record, **kwargs):
        sent = []
        Bus = type(self.env['bus.bus'])
        with patch.object(Bus, '_sendone', autospec=True,
                          side_effect=lambda bus, target, kind, payload: sent.append((kind, payload))):
            record.message_post(body='Hola', **kwargs)
        return [payload['lead_id'] for kind, payload in sent if kind == BUS_TYPE]

    def test_restaurant_reply_on_search_card_refreshes_its_lead(self):
        leads = self._post_and_capture(self.line, message_type='email', subtype_xmlid='mail.mt_comment')
        self.assertIn(self.lead.id, leads)
        self.assertNotIn(self.other_lead.id, leads)

    def test_agency_mail_on_lead_refreshes_it(self):
        self.assertIn(self.lead.id, self._post_and_capture(self.lead, message_type='email',
                                                           subtype_xmlid='mail.mt_comment'))

    def test_internal_note_does_not_refresh(self):
        self.assertFalse(self._post_and_capture(self.line, message_type='comment', subtype_xmlid='mail.mt_note'))

    def test_mail_on_sale_order_and_restaurant_sheet_refreshes_the_lead(self):
        self.line.action_toggle_chosen()
        self.lead.action_pass_to_file()
        order = self.lead._restagrup_live_orders()
        sheet = order.sudo().restaurant_po_ids[:1]
        self.assertIn(self.lead.id, self._post_and_capture(order, message_type='email',
                                                           subtype_xmlid='mail.mt_comment'))
        self.assertIn(self.lead.id, self._post_and_capture(sheet, message_type='email',
                                                           subtype_xmlid='mail.mt_comment'))
