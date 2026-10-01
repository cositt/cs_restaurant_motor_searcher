# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

SEARCH_GOOGLE = 'odoo.addons.restagrup_restaurants.models.restaurant_search.RestaurantSearch._search_google'


@tagged('post_install', '-at_install')
class TestEventSearch(TransactionCase):
    """Cada evento de un grupo (comida en Málaga, cena en Sevilla…) tiene su propia búsqueda,
    todas colgando del mismo lead."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo multi-evento'})
        cls.dinner = cls.env.ref('restagrup_core.event_type_dinner')
        cls.lunch = cls.env.ref('restagrup_core.event_type_lunch')

    def _event(self, **vals):
        defaults = {'lead_id': self.lead.id, 'city': 'Málaga', 'pax': 42, 'event_type_id': self.dinner.id,
                    'event_date': '2026-11-15'}
        defaults.update(vals)
        return self.env['restagrup.lead.event'].create(defaults)

    def _search_for(self, event):
        with patch(SEARCH_GOOGLE, return_value=[]):
            return event.action_search_restaurants()

    # --- una búsqueda por evento ---

    def test_event_search_creates_a_search_linked_to_the_event(self):
        event = self._event()
        self._search_for(event)
        search = self.env['restagrup.restaurant.search'].search([('event_id', '=', event.id)])
        self.assertEqual(len(search), 1)
        self.assertEqual(search.lead_id, self.lead)
        self.assertEqual(search.city, 'Málaga')
        self.assertEqual(search.min_capacity, 42)

    def test_event_search_marks_the_event_as_searching(self):
        event = self._event()
        self._search_for(event)
        self.assertEqual(event.state, 'searching')

    def test_searching_twice_reopens_the_same_search(self):
        event = self._event()
        self._search_for(event)
        action = self._search_for(event)
        self.assertEqual(len(event.search_ids), 1)
        self.assertEqual(action['res_id'], event.search_ids.id)

    def test_event_without_city_cannot_be_searched(self):
        event = self._event(city=False)
        with self.assertRaises(UserError):
            self._search_for(event)

    # --- buscar para todos ---

    def test_search_all_creates_one_search_per_pending_event(self):
        first = self._event(city='Málaga', event_type_id=self.lunch.id)
        self._event(city='Málaga', event_type_id=self.dinner.id)
        self._event(city='Sevilla')
        self._search_for(first)  # ya tiene búsqueda: no se duplica
        with patch(SEARCH_GOOGLE, return_value=[]):
            self.lead.action_search_all_events()
        searches = self.env['restagrup.restaurant.search'].search([('lead_id', '=', self.lead.id)])
        self.assertEqual(len(searches), 3)
        self.assertEqual(set(self.lead.restagrup_event_ids.mapped('state')), {'searching'})

    def test_search_all_skips_events_without_city(self):
        self._event(city='Málaga')
        self._event(city=False)
        with patch(SEARCH_GOOGLE, return_value=[]):
            self.lead.action_search_all_events()
        self.assertEqual(self.env['restagrup.restaurant.search'].search_count([('lead_id', '=', self.lead.id)]), 1)

    # --- el nombre de la búsqueda dice qué evento es ---

    def test_search_name_includes_event_type_and_date(self):
        event = self._event()
        self._search_for(event)
        self.assertEqual(event.search_ids.display_name, 'Málaga · 42 pax · Cena · 15/11')

    def test_search_name_without_event_is_unchanged(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid', 'min_capacity': 20,
        })
        self.assertEqual(search.display_name, 'Madrid · 20 pax')

    def test_deleting_the_search_leaves_the_event_intact(self):
        event = self._event()
        self._search_for(event)
        event.search_ids.unlink()
        self.assertTrue(event.exists())
