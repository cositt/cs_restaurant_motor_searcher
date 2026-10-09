# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

MOD = 'restagrup_service_orders'
WIZARD = 'restagrup.firewall.wizard'


@tagged('post_install', '-at_install')
class TestFirewall(TransactionCase):
    """Cortafuegos: antes de avanzar de fase el sistema avisa de lo que falta y consulta; no actúa solo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Check = cls.env['restagrup.firewall.check']
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia cortafuegos', 'email': 'ag@example.com'})
        cls.restaurant = cls.env['res.partner'].create({'name': 'Casa cortafuegos', 'is_restaurant': True})

    def _check(self, code):
        return self.Check.search([('code', '=', code)], limit=1)

    def _bare_lead(self):
        return self.env['crm.lead'].create({'name': 'Grupo vacío'})

    def _complete_lead(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo completo', 'partner_id': self.agency.id})
        self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'event_date': date.today() + timedelta(days=30), 'pax': 40})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 40})
        self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name, 'partner_id': self.restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 1000.0})
        return lead

    # --- las comprobaciones de serie ---

    def test_default_checks_exist_active_and_in_warning_mode(self):
        codes = ['agency_contact', 'services_complete', 'has_option', 'restaurant_chosen', 'pax_defined', 'paid',
                 'service_done', 'restaurant_confirmed', 'restaurant_bank', 'company_bank', 'service_datetime',
                 'restaurant_email']
        for code in codes:
            check = self._check(code)
            self.assertTrue(check, code)
            self.assertTrue(check.active, code)
            self.assertEqual(check.mode, 'warn', code)

    # --- avisar y consultar ---

    def test_incomplete_group_gets_a_warning_instead_of_moving(self):
        lead = self._bare_lead()
        action = lead.action_pass_to_quote()
        self.assertEqual(action['res_model'], WIZARD)
        self.assertEqual(lead.restagrup_stage_key, 'peticion')
        wizard = self.env[WIZARD].browse(action['res_id'])
        self.assertIn('email', wizard.message)           # agencia sin contacto
        self.assertIn('restaurante', wizard.message)     # nada que ofrecer

    def test_continuing_anyway_moves_the_group_and_leaves_a_trace(self):
        lead = self._bare_lead()
        wizard = self.env[WIZARD].browse(lead.action_pass_to_quote()['res_id'])
        wizard.action_continue()
        self.assertEqual(lead.restagrup_stage_key, 'presupuesto')
        notes = ' '.join(lead.message_ids.mapped('body'))
        self.assertIn('pese a los avisos', notes)
        self.assertIn(self.env.user.name, ' '.join(lead.message_ids.mapped('author_id.name')))

    def test_a_complete_group_moves_directly(self):
        lead = self._complete_lead()
        self.assertFalse(lead.action_pass_to_quote())
        self.assertEqual(lead.restagrup_stage_key, 'presupuesto')

    def test_block_mode_stops_the_move(self):
        self._check('has_option').mode = 'block'
        lead = self._complete_lead()
        lead.restagrup_restaurant_search_ids.line_ids.unlink()
        with self.assertRaises(UserError):
            lead.action_pass_to_quote()
        self.assertEqual(lead.restagrup_stage_key, 'peticion')

    def test_an_inactive_check_is_ignored(self):
        for code in ('agency_contact', 'services_complete', 'has_option'):
            self._check(code).active = False
        lead = self._bare_lead()
        self.assertFalse(lead.action_pass_to_quote())
        self.assertEqual(lead.restagrup_stage_key, 'presupuesto')

    def test_skip_context_bypasses_the_firewall(self):
        lead = self._bare_lead().with_context(restagrup_skip_firewall=True)
        self.assertFalse(lead.action_pass_to_quote())
        self.assertEqual(lead.restagrup_stage_key, 'presupuesto')

    def test_cancel_in_the_wizard_changes_nothing(self):
        lead = self._bare_lead()
        wizard = self.env[WIZARD].browse(lead.action_pass_to_quote()['res_id'])
        self.assertEqual(wizard.action_cancel()['type'], 'ir.actions.act_window_close')
        self.assertEqual(lead.restagrup_stage_key, 'peticion')

    # --- cada comprobación ---

    def test_pass_to_file_asks_for_a_chosen_restaurant_and_pax(self):
        lead = self._bare_lead().with_context(restagrup_skip_firewall=True)
        lead.action_pass_to_quote()
        issues = lead.with_context(restagrup_skip_firewall=False)._restagrup_firewall_issues('pass_to_file')
        self.assertEqual({i['check'].code for i in issues}, {'restaurant_chosen', 'pax_defined'})

    def test_chosen_restaurant_satisfies_pass_to_file(self):
        lead = self._complete_lead()
        search = lead.restagrup_restaurant_search_ids
        search.line_ids.action_toggle_chosen()
        issues = lead._restagrup_firewall_issues('pass_to_file')
        self.assertEqual(issues, [])
