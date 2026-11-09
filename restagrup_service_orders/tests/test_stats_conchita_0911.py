# -*- coding: utf-8 -*-
"""Estadísticas según la respuesta de Conchita (2026-11-09):
- Tiempo hasta el presupuesto (petición → propuesta enviada) y hasta el cierre del expediente.
- Por comercial, por destino y por agencia.
- Cambios: veces que se envía a la agencia un presupuesto o una proforma, después del primero de cada uno."""
from datetime import timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStatsConchita0911(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.agency = cls.env['res.partner'].create({
            'name': 'Viajes Estadística', 'is_company': True, 'email': 'agencia@example.com'})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Marta Datos', 'parent_id': cls.agency.id, 'email': 'marta@example.com'})

    def _lead(self, **vals):
        return self.env['crm.lead'].create(dict({'name': 'Grupo stats', 'partner_id': self.contact.id}, **vals))

    def _order(self, lead):
        return self.env['sale.order'].create({'partner_id': self.contact.id, 'opportunity_id': lead.id})

    # --- tiempo hasta el cierre ---

    def test_close_date_is_recorded_once(self):
        lead = self._lead()
        lead._restagrup_move_to('expediente')
        self.assertFalse(lead.restagrup_close_date)
        lead._restagrup_move_to('cerrado')
        first = lead.restagrup_close_date
        self.assertTrue(first)
        lead._restagrup_move_to('expediente')
        lead._restagrup_move_to('cerrado')
        self.assertEqual(lead.restagrup_close_date, first)

    def test_hours_to_close(self):
        lead = self._lead()
        lead.write({'restagrup_close_date': lead.create_date + timedelta(hours=100)})
        self.assertAlmostEqual(lead.restagrup_hours_to_close, 100.0)
        self.assertEqual(self.env['crm.lead']._fields['restagrup_hours_to_close'].aggregator, 'avg')

    # --- proformas enviadas a la agencia ---

    def test_sending_the_sale_order_to_the_agency_counts_a_proforma(self):
        lead = self._lead()
        order = self._order(lead)
        order.with_context(mark_so_as_sent=True).message_post(body='Proforma', message_type='comment')
        order.with_context(mark_so_as_sent=True).message_post(body='Proforma 2', message_type='comment')
        self.assertEqual(lead.restagrup_proformas_sent, 2)

    def test_internal_notes_do_not_count(self):
        lead = self._lead()
        self._order(lead).message_post(body='Nota interna')
        self.assertEqual(lead.restagrup_proformas_sent, 0)

    def test_updated_proforma_after_changes_counts(self):
        lead = self._lead()
        order = self._order(lead)
        order._restagrup_send_updated_proforma([])
        self.assertEqual(lead.restagrup_proformas_sent, 1)

    def test_changes_count_resent_quotes_and_proformas(self):
        lead = self._lead()
        lead.write({'restagrup_proposals_sent': 2, 'restagrup_proformas_sent': 3})
        self.assertEqual(lead.restagrup_quote_changes, 1 + 2)

    def test_first_quote_and_first_proforma_are_not_changes(self):
        lead = self._lead()
        lead.write({'restagrup_proposals_sent': 1, 'restagrup_proformas_sent': 1})
        self.assertEqual(lead.restagrup_quote_changes, 0)

    # --- por destino y por agencia ---

    def test_destination_is_the_first_service_city(self):
        lead = self._lead()
        self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Granada', 'pax': 20, 'event_date': '2027-03-02'})
        self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'pax': 20, 'event_date': '2027-03-01'})
        self.assertEqual(lead.restagrup_destination, 'Sevilla')
        self.assertTrue(self.env['crm.lead']._fields['restagrup_destination'].store)

    def test_agency_is_the_contacts_company(self):
        lead = self._lead()
        self.assertEqual(lead.restagrup_agency_id, self.agency)
        self.assertTrue(self.env['crm.lead']._fields['restagrup_agency_id'].store)

    def test_statistics_can_be_grouped_by_destination_and_agency(self):
        self._lead()
        Lead = self.env['crm.lead']
        for field in ('restagrup_destination', 'restagrup_agency_id'):
            groups = Lead._read_group([('partner_id', '=', self.contact.id)], [field], ['restagrup_quote_changes:avg'])
            self.assertTrue(groups)
        pivot = Lead.get_view(self.env.ref('restagrup_service_orders.view_restagrup_statistics_pivot').id,
                              'pivot')['arch']
        for field in ('restagrup_hours_to_close', 'restagrup_proposals_sent', 'restagrup_proformas_sent'):
            self.assertIn('name="%s"' % field, pivot)
        search = Lead.get_view(self.env.ref('restagrup_service_orders.view_restagrup_statistics_search').id,
                               'search')['arch']
        for field in ('user_id', 'restagrup_destination', 'restagrup_agency_id'):
            self.assertIn('name="%s"' % field, search)
