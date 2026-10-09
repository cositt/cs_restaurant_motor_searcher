# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

EXTRACT = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
INCOMPLETE = {'ciudad': 'Sevilla', 'num_pax': 45, 'fecha_servicio': None, 'tipo_grupo': 'senior',
              'eventos': [{'ciudad': 'Sevilla', 'fecha': None, 'pax': 45, 'tipo': 'comida', 'notas': ''}]}
PRICES = {'Taberna del Patio Andaluz': 26.0, 'Casa Giralda Grupos': 28.0, 'Bodega San Telmo': 24.5}


@tagged('post_install', '-at_install')
class TestDemo2Guide(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.guide = cls.env['restagrup.demo2.guide']
        cls.guide.reset_demo()  # independiente de lo que haya en la BD (todo se deshace al acabar el test)
        cls.restaurants = {}
        for name in PRICES:
            partner = cls.env['res.partner'].create({
                'name': name, 'is_restaurant': True, 'email': 'reservas@%s.demo' % name.split()[0].lower(),
                'city': 'Sevilla'})
            cls.env['restagrup.restaurant.menu'].create({
                'name': 'Menú 2026', 'partner_id': partner.id, 'season': 2026, 'cost_price': PRICES[name],
                'description': 'Entrantes, principal, postre y bebidas incluidas.'})
            cls.restaurants[name] = partner

    # --- ayudas ---

    def _arrive(self):
        with patch(EXTRACT, return_value=(INCOMPLETE, 'groq')):
            return self.guide.simulate_agency_email()

    def _pending(self, lead):
        return self.env['restagrup.pending.mail'].search([('request_lead_id', '=', lead.id)])

    def _approved_lead(self):
        lead = self.env['crm.lead'].browse(self._arrive())
        self._pending(lead).action_approve()
        return lead

    def _completed_lead(self):
        lead = self._approved_lead()
        reply = {'eventos': [{'id': lead.restagrup_event_ids[:1].id, 'fecha': '2026-12-11'}]}
        with patch(EXTRACT, return_value=(reply, 'groq')):
            self.guide.simulate_agency_reply()
        return lead

    def _search(self, lead):
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 45})
        for name, partner in self.restaurants.items():
            self.env['restagrup.restaurant.search.line'].create({
                'search_id': search.id, 'source': 'partner', 'name': name, 'partner_id': partner.id,
                'email': partner.email})
        return search

    def _quoted_search(self):
        lead = self._completed_lead()
        search = self._search(lead)
        self.guide.request_quotes()
        replies = [({'importe': price * 45, 'notas': 'Menú de grupo'}, 'groq') for price in PRICES.values()]
        with patch(EXTRACT, side_effect=replies):
            self.guide.simulate_restaurant_replies()
        return lead, search

    # --- petición incompleta ---

    def test_incomplete_email_creates_a_lead_and_queues_the_data_request(self):
        lead = self.env['crm.lead'].browse(self._arrive())
        self.assertEqual(lead.restagrup_pax, 45)
        self.assertTrue(lead._restagrup_missing_request_data())
        pending = self._pending(lead)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending.state, 'pending')
        self.assertIn('Fecha', pending.body)
        self.assertNotIn('Ciudad', pending.body)  # solo lo que falta

    def test_agency_email_is_idempotent(self):
        first = self._arrive()
        self.assertEqual(self._arrive(), first)
        self.assertEqual(self.env['crm.lead'].search_count([('email_from', 'ilike', 'costaviajes')]), 1)

    def test_reply_needs_the_request_to_be_sent_first(self):
        self._arrive()
        with self.assertRaises(UserError):
            self.guide.simulate_agency_reply()

    def test_agency_reply_completes_the_lead(self):
        lead = self._completed_lead()
        self.assertFalse(lead._restagrup_missing_request_data())
        self.assertEqual(str(lead.restagrup_event_ids[:1].event_date), '2026-12-11')
        self.assertTrue(self.guide.get_state()['done']['reply'])

    def test_state_follows_the_walkthrough(self):
        self.assertFalse(self.guide.get_state()['done']['email'])
        lead = self.env['crm.lead'].browse(self._arrive())
        done = self.guide.get_state()['done']
        self.assertTrue(done['email'] and done['ask'])
        self.assertFalse(done['approve'] or done['reply'])
        self._pending(lead).action_approve()
        self.assertTrue(self.guide.get_state()['done']['approve'])

    # --- varias opciones ---

    def test_request_quotes_needs_a_search_first(self):
        self._completed_lead()
        with self.assertRaises(UserError):
            self.guide.request_quotes()

    def test_request_quotes_asks_the_three_restaurants(self):
        lead = self._completed_lead()
        search = self._search(lead)
        self.guide.request_quotes()
        self.assertTrue(all(search.line_ids.mapped('quote_requested_date')))
        self.assertTrue(self.guide.get_state()['done']['request'])

    def test_restaurant_replies_carry_amount_and_menu(self):
        lead, search = self._quoted_search()
        for line in search.line_ids:
            self.assertAlmostEqual(line.quote_amount, PRICES[line.name] * 45)
            self.assertEqual(line.menu_id.partner_id, line.partner_id)
            self.assertEqual(line.etiqueta, 'solicitado')  # propuesto por la IA, sin confirmar
        self.assertTrue(self.guide.get_state()['done']['answers'])

    def test_confirming_registers_the_three_quotes(self):
        lead, search = self._quoted_search()
        self.guide.confirm_quotes()
        self.assertEqual(set(search.line_ids.mapped('etiqueta')), {'presupuesto_recibido'})
        self.assertEqual(len(search.restagrup_comparison_rows()), 3)
        self.assertTrue(self.guide.get_state()['done']['confirm'])

    def test_toggle_visible_hides_and_shows_the_names(self):
        lead, search = self._quoted_search()
        self.guide.confirm_quotes()
        self.assertFalse(self.guide.toggle_visible())
        self.assertEqual([row['name'] for row in search.restagrup_comparison_rows()][:1], ['Opción 1'])
        self.assertTrue(self.guide.toggle_visible())

    # --- confirmaciones ---

    def test_gratuities_are_applied_once(self):
        lead, search = self._quoted_search()
        self.guide.confirm_quotes()
        search.line_ids.sorted('quote_amount')[:1].action_toggle_chosen()
        search.action_create_sale_order()
        self.guide.apply_gratuities()
        self.guide.apply_gratuities()
        line = search.sale_order_id.order_line.filtered('restaurant_id')
        self.assertEqual((line.product_uom_qty, line.restagrup_gratuities), (43, 2))
        self.assertGreater(line.price_unit, 0)  # al bajar los que pagan, el precio no se pierde
        self.assertTrue(self.guide.get_state()['done']['docs'])

    def test_gratuities_need_the_sale_order(self):
        self._quoted_search()
        with self.assertRaises(UserError):
            self.guide.apply_gratuities()

    # --- reinicio ---

    def test_reset_removes_the_walkthrough_but_keeps_the_sample_documents(self):
        other = self.env['crm.lead'].create({'name': 'Documento de ejemplo'})
        self._quoted_search()
        self.guide.reset_demo()
        self.assertFalse(self.guide._lead())
        self.assertTrue(other.exists())
        self.assertFalse(self.guide.get_state()['done']['email'])
