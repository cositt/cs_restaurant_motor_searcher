# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase, tagged

WEEKDAY = date(2026, 10, 14)  # miércoles
SATURDAY = date(2026, 10, 17)


@tagged('post_install', '-at_install')
class TestPriceBaseline(TransactionCase):

    def setUp(self):
        super().setUp()
        self.baseline = self.env['restagrup.price.baseline']
        self.lunch = self.env.ref('restagrup_core.event_type_lunch')
        self.dinner = self.env.ref('restagrup_core.event_type_dinner')
        self.breakfast = self.env.ref('restagrup_core.event_type_breakfast')

    def test_seeded_baselines_follow_the_client_references(self):
        self.assertEqual(self.baseline.estimate(self.lunch, WEEKDAY), 16.0)
        self.assertEqual(self.baseline.estimate(self.lunch, SATURDAY), 18.5)
        self.assertEqual(self.baseline.estimate(self.dinner, WEEKDAY), 20.0)
        self.assertEqual(self.baseline.estimate(self.breakfast, WEEKDAY), 5.0)
        self.assertEqual(self.baseline.estimate(self.lunch, WEEKDAY, audience='students'), 14.5)
        self.assertEqual(self.baseline.estimate(self.lunch, WEEKDAY, audience='athletes'), 16.0)

    def test_no_matching_baseline_gives_zero_not_an_error(self):
        other = self.env.ref('restagrup_core.event_type_other')
        self.assertEqual(self.baseline.estimate(other, WEEKDAY), 0.0)
        self.assertEqual(self.baseline.estimate(self.env['restagrup.event.type'], WEEKDAY), 0.0)

    def test_city_baseline_wins_over_the_generic_one(self):
        self.baseline.create({
            'name': 'Comida La Rioja', 'event_type_id': self.lunch.id, 'day_type': 'any',
            'city': 'Logroño', 'price_pp': 19.0,
        })
        self.assertEqual(self.baseline.estimate(self.lunch, WEEKDAY, city='logroño'), 19.0)
        self.assertEqual(self.baseline.estimate(self.lunch, WEEKDAY, city='Tordesillas'), 16.0)

    def test_inactive_baseline_is_ignored(self):
        generic = self.baseline.search([
            ('event_type_id', '=', self.breakfast.id), ('audience', '=', 'adults'),
        ])
        generic.active = False
        self.assertEqual(self.baseline.estimate(self.breakfast, WEEKDAY), 0.0)

    def test_internal_user_can_read_baselines_but_not_delete(self):
        user = self.env['res.users'].create({
            'name': 'Interno baremos', 'login': 'interno_baremos',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        model = self.baseline.with_user(user)
        self.assertTrue(model.has_access('read'))
        self.assertTrue(model.has_access('write'))
        self.assertFalse(model.has_access('unlink'))
