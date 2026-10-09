# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEventEstimate(TransactionCase):

    def setUp(self):
        super().setUp()
        self.lead = self.env['crm.lead'].create({'name': 'Grupo de prueba'})
        self.lunch = self.env.ref('restagrup_core.event_type_lunch')
        self.dinner = self.env.ref('restagrup_core.event_type_dinner')

    def _event(self, **vals):
        base = {'lead_id': self.lead.id, 'event_type_id': self.lunch.id, 'event_date': '2026-10-14', 'pax': 30}
        return self.env['restagrup.lead.event'].create({**base, **vals})

    def test_event_without_budget_gets_the_baseline_marked_as_estimate(self):
        event = self._event()
        self.assertEqual(event.budget_pp, 16.0)
        self.assertTrue(event.budget_is_estimate)

    def test_budget_given_by_the_agency_is_kept_and_not_an_estimate(self):
        event = self._event(budget_pp=24.0)
        self.assertEqual(event.budget_pp, 24.0)
        self.assertFalse(event.budget_is_estimate)

    def test_editing_the_estimate_by_hand_makes_it_a_real_figure(self):
        event = self._event()
        event.budget_pp = 17.5
        self.assertEqual(event.budget_pp, 17.5)
        self.assertFalse(event.budget_is_estimate)
        event.event_type_id = self.dinner
        self.assertEqual(event.budget_pp, 17.5, 'un precio manual no se pisa al cambiar el evento')

    def test_estimate_follows_the_event_while_it_is_still_an_estimate(self):
        event = self._event()
        event.event_date = '2026-10-17'  # sábado
        self.assertEqual(event.budget_pp, 18.5)
        event.event_type_id = self.dinner
        self.assertEqual(event.budget_pp, 20.0)
        self.assertTrue(event.budget_is_estimate)

    def test_audience_changes_the_estimate(self):
        event = self._event(audience='students')
        self.assertEqual(event.budget_pp, 14.5)

    def test_no_baseline_leaves_budget_empty_and_does_not_block(self):
        event = self._event(event_type_id=self.env.ref('restagrup_core.event_type_other').id)
        self.assertEqual(event.budget_pp, 0.0)
        self.assertFalse(event.budget_is_estimate)

    def test_clearing_the_budget_goes_back_to_the_estimate(self):
        event = self._event(budget_pp=24.0)
        event.budget_pp = 0.0
        self.assertEqual(event.budget_pp, 16.0)
        self.assertTrue(event.budget_is_estimate)

    def test_date_filled_in_later_triggers_the_estimate(self):
        event = self._event(event_date=False)
        self.assertEqual(event.budget_pp, 0.0)
        event.event_date = '2026-12-11'  # viernes: la IA completa la fecha tras la respuesta de la agencia
        self.assertEqual(event.budget_pp, 16.0)
        self.assertTrue(event.budget_is_estimate)

    def test_manual_zero_budget_is_not_overwritten_by_other_edits_when_no_baseline(self):
        event = self._event(event_type_id=self.env.ref('restagrup_core.event_type_other').id)
        event.pax = 50
        self.assertEqual(event.budget_pp, 0.0)
