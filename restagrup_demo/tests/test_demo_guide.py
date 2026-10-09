# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

EXTRACT = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
LEAD_DATA = {'ciudad': 'Málaga', 'num_pax': 32, 'fecha_servicio': '2026-11-13', 'tipo_grupo': 'cultural',
             'eventos': [{'ciudad': 'Málaga', 'fecha': '2026-11-13', 'pax': 32, 'tipo': 'comida', 'notas': ''}]}


@tagged('post_install', '-at_install')
class TestDemoGuide(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.guide = cls.env['restagrup.demo.guide']
        cls.guide.reset_demo()  # independiente de lo que haya en la BD (todo se deshace al acabar el test)
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Asador Sierra Blanca', 'is_restaurant': True, 'email': 'reservas@asador.demo', 'city': 'Málaga',
        })

    def _arrive(self):
        with patch(EXTRACT, return_value=(LEAD_DATA, 'groq')):
            return self.guide.simulate_agency_email()

    def _search_with_request(self):
        lead = self.env['crm.lead'].browse(self._arrive())
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Málaga', 'min_capacity': 32})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Asador Sierra Blanca',
            'partner_id': self.restaurant.id, 'email': 'reservas@asador.demo',
        })
        line.action_request_quote()
        return lead, search, line

    def test_agency_email_creates_a_lead_with_ai_data(self):
        lead = self.env['crm.lead'].browse(self._arrive())
        self.assertTrue(lead)
        self.assertEqual(lead.restagrup_pax, 32)
        self.assertEqual(lead.restagrup_extraction_state, 'done')
        self.assertEqual(len(lead.restagrup_event_ids), 1)

    def test_agency_email_is_idempotent(self):
        first = self._arrive()
        self.assertEqual(self._arrive(), first)
        self.assertEqual(self.env['crm.lead'].search_count([('email_from', 'ilike', 'sunriseheritage')]), 1)

    def test_state_follows_the_walkthrough(self):
        self.assertFalse(self.guide.get_state()['done']['email'])
        lead, search, line = self._search_with_request()
        done = self.guide.get_state()['done']
        self.assertTrue(done['email'] and done['ai'] and done['search'] and done['request'])
        self.assertFalse(done['reply'] or done['chosen'] or done['order'])

    def test_reply_requires_a_request_first(self):
        self._arrive()
        with self.assertRaises(UserError):
            self.guide.simulate_restaurant_reply()

    def test_reply_arrives_in_the_same_thread_and_proposes_the_amount(self):
        lead, search, line = self._search_with_request()
        with patch(EXTRACT, return_value=({'importe': 1024.0, 'notas': 'Menú de grupo'}, 'groq')):
            self.guide.simulate_restaurant_reply()
        self.assertAlmostEqual(line.quote_amount, 1024.0)
        self.assertEqual(line.etiqueta, 'solicitado')  # propuesto por la IA, sin confirmar
        self.assertTrue(self.guide.get_state()['done']['reply'])

    def test_reply_is_idempotent(self):
        lead, search, line = self._search_with_request()
        with patch(EXTRACT, return_value=({'importe': 1024.0}, 'groq')):
            self.guide.simulate_restaurant_reply()
            self.guide.simulate_restaurant_reply()
        replies = line.message_ids.filtered(lambda m: m.message_type == 'email' and m.email_from and 'asador' in m.email_from.lower())
        self.assertEqual(len(replies), 1)

    def test_reset_clears_the_walkthrough_but_keeps_the_restaurants(self):
        self._search_with_request()
        self.guide.reset_demo()
        done = self.guide.get_state()['done']
        self.assertFalse(any(done.values()))
        self.assertTrue(self.restaurant.exists())

    def test_reset_clears_a_confirmed_order_with_its_service_sheet(self):
        lead, search, line = self._search_with_request()
        line.write({'etiqueta': 'presupuesto_recibido', 'quote_amount': 1024})
        line.action_toggle_chosen()
        search.action_create_sale_order()
        order = search.sale_order_id
        order.action_confirm()
        self.assertTrue(order.restaurant_po_ids)
        done = self.guide.get_state()['done']
        self.assertTrue(done['order'] and done['signed'] and done['sheet'])
        self.guide.reset_demo()
        self.assertFalse(self.env['sale.order'].search([]))
        self.assertFalse(self.env['purchase.order'].search([]))
        self.assertFalse(any(self.guide.get_state()['done'].values()))

    def test_reset_is_blocked_outside_the_demo_database(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup_demo.enabled', '0')
        with self.assertRaises(UserError):
            self.guide.reset_demo()
