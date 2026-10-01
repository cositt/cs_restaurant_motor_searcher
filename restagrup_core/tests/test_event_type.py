# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

SEEDED = {
    'restagrup_core.event_type_breakfast': 'Desayuno',
    'restagrup_core.event_type_aperitif': 'Aperitivo',
    'restagrup_core.event_type_lunch': 'Comida',
    'restagrup_core.event_type_dinner': 'Cena',
    'restagrup_core.event_type_coffee_break': 'Coffee break',
    'restagrup_core.event_type_other': 'Otro',
}


@tagged('post_install', '-at_install')
class TestEventType(TransactionCase):

    def test_initial_event_types_are_loaded(self):
        for xmlid, name in SEEDED.items():
            self.assertEqual(self.env.ref(xmlid).name, name, xmlid)

    def test_event_types_are_ordered_by_sequence(self):
        types = self.env['restagrup.event.type'].search([('id', 'in', [self.env.ref(x).id for x in SEEDED])])
        self.assertEqual(types[0].name, 'Desayuno')

    def test_a_new_event_type_can_be_added_and_archived(self):
        new_type = self.env['restagrup.event.type'].create({'name': 'Brunch'})
        self.assertTrue(new_type.active)
        new_type.active = False
        self.assertNotIn(new_type, self.env['restagrup.event.type'].search([]))

    def test_internal_user_can_read_and_create_event_types(self):
        user = self.env['res.users'].create({
            'name': 'Interno tipos', 'login': 'interno_tipos',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        types = self.env['restagrup.event.type'].with_user(user)
        self.assertTrue(types.search([]))
        self.assertTrue(types.create({'name': 'Merienda'}))
