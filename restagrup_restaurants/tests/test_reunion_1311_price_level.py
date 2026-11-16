# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion1311PriceLevel(TransactionCase):
    """Reunión 13/11 (P9): semáforo del precio frente al estimado (dentro / justo / se pasa) y confirmación al
    elegir un restaurante que se pasa."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.commission_pct', 0)
        lead = cls.env['crm.lead'].create({'name': 'Grupo semáforo'})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': '2026-12-15', 'budget_pp': 20.0,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'event_id': cls.event.id, 'city': 'Madrid', 'min_capacity': 30})

    def _line(self, agency_price):
        restaurant = self.env['res.partner'].create({'name': 'Casa %s' % agency_price, 'is_restaurant': True})
        line = self.env[LINE].create({
            'search_id': self.search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': agency_price,
            'quote_received_date': '2026-11-16 10:00:00'})
        # el precio a la agencia lleva la comisión: se fuerza al valor del test para no depender de Ajustes
        return line, line.quote_client_price_per_person

    def _status_for_agency_price(self, wanted):
        line, price = self._line(wanted)
        return line, line.price_level_status, price

    def test_levels_follow_the_agency_price(self):
        budget = self.search.budget_pp
        seen = set()
        for line in (self._line(p)[0] for p in (10, 16, 18, 19, 20, 22, 30)):
            price = line.quote_client_price_per_person
            expected = 'ok' if price <= budget else ('near' if price <= budget * 1.15 else 'over')
            self.assertEqual(line.price_level_status, expected, price)
            seen.add(expected)
        self.assertEqual(seen, {'ok', 'near', 'over'})

    def test_without_estimate_there_is_no_colour(self):
        self.search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.search.lead_id.id, 'city': 'Madrid', 'min_capacity': 30})  # sin servicio: sin estimado
        line = self._line(50)[0]
        self.assertFalse(line.search_id.budget_pp)
        self.assertFalse(line.price_level_status)

    def _over_line(self):
        line = self._line(40)[0]
        self.assertEqual(line.price_level_status, 'over')
        return line

    def test_choosing_an_over_budget_restaurant_asks_first(self):
        line = self._over_line()
        action = line.with_context(restagrup_price_check=True).action_toggle_chosen()
        self.assertEqual(action['res_model'], 'restagrup.choose.over.budget')
        self.assertFalse(self.search.chosen_line_id)
        wizard = self.env['restagrup.choose.over.budget'].browse(action['res_id'])
        self.assertIn('Se pasa', wizard.message)

    def test_confirming_chooses_it_and_leaves_a_note(self):
        line = self._over_line()
        action = line.with_context(restagrup_price_check=True).action_toggle_chosen()
        self.env['restagrup.choose.over.budget'].browse(action['res_id']).action_confirm()
        self.assertEqual(self.search.chosen_line_id, line)
        self.assertTrue(self.search.lead_id.message_ids.filtered(lambda m: 'precio estimado' in (m.body or ''))
                        or self.search.message_ids.filtered(lambda m: 'precio estimado' in (m.body or '')))

    def test_choosing_from_code_does_not_ask(self):
        line = self._over_line()
        self.assertFalse(line.action_toggle_chosen())
        self.assertEqual(self.search.chosen_line_id, line)

    def test_choose_buttons_ask_for_the_price_check(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertNotIn('name="action_toggle_chosen" type="object" class', arch)
        self.assertIn("restagrup_price_check", arch)

    def test_choosing_within_budget_does_not_ask(self):
        line = self._line(10)[0]
        self.assertFalse(line.with_context(restagrup_price_check=True).action_toggle_chosen())
        self.assertEqual(self.search.chosen_line_id, line)
