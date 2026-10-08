# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

MOD = 'restagrup_service_orders'


@tagged('post_install', '-at_install')
class TestLeadStages(TransactionCase):
    """El grupo vive en una sola ficha que cambia de fase: Petición → Presupuesto → Expediente → Cerrado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env['crm.lead'].with_context(restagrup_skip_firewall=True)  # aquí se prueban las fases, no los avisos
        cls.stage = {key: cls.env.ref('%s.stage_%s' % (MOD, key)) for key in
                     ('peticion', 'presupuesto', 'expediente', 'cerrado')}

    def _lead(self, **vals):
        vals.setdefault('name', 'Grupo etapas')
        return self.Lead.create(vals)

    # --- etapas ---

    def test_stages_follow_the_clients_flow(self):
        ordered = sorted(self.stage.values(), key=lambda s: s.sequence)
        self.assertEqual([s.name for s in ordered], ['Petición', 'Presupuesto', 'Expediente', 'Cerrado'])
        self.assertEqual([s.restagrup_doc_prefix for s in ordered], ['PET', 'PRE', 'EXP', 'EXP'])
        self.assertTrue(self.stage['cerrado'].is_won)

    def test_new_lead_starts_as_peticion(self):
        self.assertEqual(self._lead().stage_id, self.stage['peticion'])

    def test_old_default_stages_are_after_ours(self):
        old = self.env.ref('crm.stage_lead1')
        self.assertGreater(old.sequence, self.stage['cerrado'].sequence)

    # --- numeración ---

    def test_number_has_the_clients_format(self):
        lead = self._lead()
        month = lead.create_date.strftime('%Y%m')
        self.assertEqual(lead.restagrup_doc_number, 'PET%s-%s' % (month, lead.restagrup_doc_seq))
        self.assertGreaterEqual(lead.restagrup_doc_seq, 17711)

    def test_numbers_are_unique_and_increasing(self):
        first, second = self._lead(), self._lead()
        self.assertEqual(second.restagrup_doc_seq, first.restagrup_doc_seq + 1)
        self.assertNotEqual(first.restagrup_doc_number, second.restagrup_doc_number)

    def test_prefix_changes_with_the_stage_but_the_sequence_stays(self):
        lead = self._lead()
        seq, month = lead.restagrup_doc_seq, lead.create_date.strftime('%Y%m')
        lead.action_pass_to_quote()
        self.assertEqual(lead.restagrup_doc_number, 'PRE%s-%s' % (month, seq))
        lead.action_pass_to_file()
        self.assertEqual(lead.restagrup_doc_number, 'EXP%s-%s' % (month, seq))
        lead.action_close_file()
        self.assertEqual(lead.restagrup_doc_number, 'EXP%s-%s' % (month, seq))

    def test_copy_gets_its_own_number(self):
        lead = self._lead()
        self.assertNotEqual(lead.copy().restagrup_doc_seq, lead.restagrup_doc_seq)

    # --- transiciones ---

    def test_pass_to_quote_only_from_peticion(self):
        lead = self._lead()
        lead.action_pass_to_quote()
        self.assertEqual(lead.stage_id, self.stage['presupuesto'])
        with self.assertRaises(UserError):
            lead.action_pass_to_quote()

    def test_pass_to_file_from_peticion_or_presupuesto(self):
        direct = self._lead()
        direct.action_pass_to_file()
        self.assertEqual(direct.stage_id, self.stage['expediente'])
        quoted = self._lead()
        quoted.action_pass_to_quote()
        quoted.action_pass_to_file()
        self.assertEqual(quoted.stage_id, self.stage['expediente'])
        with self.assertRaises(UserError):
            direct.action_pass_to_file()

    def test_close_file_only_from_expediente_and_marks_it_won(self):
        lead = self._lead()
        with self.assertRaises(UserError):
            lead.action_close_file()
        lead.action_pass_to_file()
        lead.action_close_file()
        self.assertEqual(lead.stage_id, self.stage['cerrado'])
        self.assertEqual(lead.probability, 100.0)

    def test_every_change_leaves_a_note_in_the_chatter(self):
        lead = self._lead()
        lead.action_pass_to_quote()
        self.assertTrue(any('Presupuesto' in (m.body or '') for m in lead.message_ids))

    def test_confirming_the_sale_order_moves_the_group_to_expediente(self):
        partner = self.env['res.partner'].create({'name': 'Agencia etapas', 'email': 'ag@example.com'})
        lead = self._lead(partner_id=partner.id)
        lead.action_pass_to_quote()
        order = self.env['sale.order'].create({
            'partner_id': partner.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.env.ref('%s.product_restaurant_service' % MOD).id,
                                   'product_uom_qty': 10, 'price_unit': 20.0})]})
        order.action_confirm()
        self.assertEqual(lead.stage_id, self.stage['expediente'])

    def test_confirming_does_not_reopen_a_closed_group(self):
        partner = self.env['res.partner'].create({'name': 'Agencia cerrada', 'email': 'ag2@example.com'})
        lead = self._lead(partner_id=partner.id)
        lead.action_pass_to_file()
        lead.action_close_file()
        order = self.env['sale.order'].create({
            'partner_id': partner.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.env.ref('%s.product_restaurant_service' % MOD).id,
                                   'product_uom_qty': 5, 'price_unit': 10.0})]})
        order.action_confirm()
        self.assertEqual(lead.stage_id, self.stage['cerrado'])

    # --- datos para las listas ---

    def test_first_service_and_total_pax_come_from_the_events(self):
        lead = self._lead()
        Event = self.env['restagrup.lead.event']
        Event.create({'lead_id': lead.id, 'city': 'Sevilla', 'event_date': '2026-11-20', 'pax': 30})
        Event.create({'lead_id': lead.id, 'city': 'Granada', 'event_date': '2026-11-15', 'pax': 20})
        self.assertEqual(str(lead.restagrup_first_service_date), '2026-11-15')
        self.assertEqual(lead.restagrup_first_service_city, 'Granada')
        self.assertEqual(lead.restagrup_total_pax, 50)

    def test_without_events_the_loose_lead_data_are_used(self):
        lead = self._lead(restagrup_city='Toledo', restagrup_pax=40, restagrup_service_date='2026-12-01')
        self.assertEqual(lead.restagrup_first_service_city, 'Toledo')
        self.assertEqual(lead.restagrup_total_pax, 40)
        self.assertEqual(str(lead.restagrup_first_service_date), '2026-12-01')

    def test_lead_form_drops_the_sales_funnel_and_names_the_reject_button(self):
        arch = self.env['crm.lead'].get_view(self.env.ref('crm.crm_lead_view_form').id)['arch']
        self.assertIn('Rechazar presupuesto', arch)
        self.assertNotIn('>Perdido<', arch.replace('string="Perdido"', ''))
        self.assertRegex(arch, r'name="action_set_won_rainbowman"[^>]*invisible="1"|invisible="1"[^>]*name="action_set_won_rainbowman"')

    def test_agency_name_falls_back_to_what_the_email_gave(self):
        agency = self.env['res.partner'].create({'name': 'Agencia ficha'})
        self.assertEqual(self._lead(partner_id=agency.id).restagrup_agency_name, 'Agencia ficha')
        self.assertEqual(self._lead(partner_name='Costa Viajes').restagrup_agency_name, 'Costa Viajes')
        self.assertEqual(self._lead(contact_name='Lucía Prieto').restagrup_agency_name, 'Lucía Prieto')
        self.assertEqual(self._lead(email_from='Lucía <lucia@costaviajes.demo>').restagrup_agency_name, 'Lucía')
        self.assertEqual(self._lead(email_from='lucia@costaviajes.demo').restagrup_agency_name, 'lucia@costaviajes.demo')
        self.assertFalse(self._lead().restagrup_agency_name)

    # --- migración de los leads que ya existían ---

    def test_backfill_numbers_and_moves_old_default_stages(self):
        new = self._lead()
        old = self._lead(name='Viejo')
        old.write({'stage_id': self.env.ref('crm.stage_lead2').id})
        self.env.cr.execute('update crm_lead set restagrup_doc_seq = null where id = %s', [old.id])
        old.invalidate_recordset()
        self.Lead._restagrup_backfill_documents()
        self.assertTrue(old.restagrup_doc_seq)
        self.assertEqual(old.stage_id, self.stage['presupuesto'])
        self.assertEqual(new.stage_id, self.stage['peticion'])

    def test_list_actions_show_each_stage(self):
        lead = self._lead()
        for xmlid, expected in (('action_peticiones', True), ('action_presupuestos', False)):
            action = self.env.ref('%s.%s' % (MOD, xmlid))
            from odoo.tools.safe_eval import safe_eval
            domain = safe_eval(action.domain, {'ref': lambda x: self.env.ref(x).id}) if action.domain else []
            self.assertEqual(bool(self.Lead.search([('id', '=', lead.id)] + domain)), expected, xmlid)
