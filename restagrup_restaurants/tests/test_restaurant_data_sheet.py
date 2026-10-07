# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

MONDAY = date(2026, 10, 12)
TUESDAY = date(2026, 10, 13)


@tagged('post_install', '-at_install')
class TestRestaurantDataSheet(TransactionCase):
    """A3: ficha de restaurante completa, avisos en el buscador y petición de los datos que faltan."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Line = cls.env['restagrup.restaurant.search.line']
        cls.Pending = cls.env['restagrup.pending.mail']
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo A3'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 40,
        })

    def _complete_vals(self, **extra):
        vals = {
            'name': 'Casa Completa', 'is_restaurant': True, 'email': 'casa@example.com',
            'restaurant_capacity': 80, 'restaurant_closed_weekday': 'none',
            'restaurant_language': 'es', 'restaurant_group_manager': 'Marta',
            'restaurant_group_mobile': '600000000',
        }
        vals.update(extra)
        return vals

    def _line(self, partner, **vals):
        defaults = {
            'search_id': self.search.id, 'source': 'partner', 'name': partner.name,
            'partner_id': partner.id, 'email': partner.email,
            'capacity': partner.restaurant_capacity,
        }
        defaults.update(vals)
        return self.Line.create(defaults)

    # --- campos de la ficha ---

    def test_new_fields_exist_with_email_as_default_channel(self):
        partner = self.Partner.create(self._complete_vals(restaurant_gratuities='1 por cada 25'))
        self.assertEqual(partner.restaurant_gratuities, '1 por cada 25')
        self.assertEqual(partner.restaurant_preferred_channel, 'email')

    def test_closed_weekday_accepts_none(self):
        partner = self.Partner.create(self._complete_vals(restaurant_closed_weekday='none'))
        self.assertEqual(partner.restaurant_closed_weekday, 'none')

    # --- ficha incompleta ---

    def test_empty_restaurant_is_incomplete_and_lists_missing_fields(self):
        partner = self.Partner.create({'name': 'Casa Vacía', 'is_restaurant': True})
        self.assertTrue(partner.restaurant_is_incomplete)
        for label in ('Aforo (grupos)', 'Día de cierre', 'Idioma', 'Responsable de grupos', 'Móvil del responsable'):
            self.assertIn(label, partner.restaurant_missing_fields)

    def test_complete_restaurant_has_nothing_missing(self):
        partner = self.Partner.create(self._complete_vals())
        self.assertFalse(partner.restaurant_is_incomplete)
        self.assertFalse(partner.restaurant_missing_fields)

    def test_no_closing_day_counts_as_filled_but_empty_does_not(self):
        partner = self.Partner.create(self._complete_vals(restaurant_closed_weekday=False))
        self.assertIn('Día de cierre', partner.restaurant_missing_fields)

    def test_non_restaurant_is_never_incomplete(self):
        partner = self.Partner.create({'name': 'Persona'})
        self.assertFalse(partner.restaurant_is_incomplete)

    def test_line_shows_incomplete_from_its_partner(self):
        partner = self.Partner.create({'name': 'Casa Vacía 2', 'is_restaurant': True, 'email': 'v@example.com'})
        line = self._line(partner)
        self.assertTrue(line.partner_incomplete)
        self.assertIn('Idioma', line.missing_fields_text)

    def test_google_line_without_partner_is_not_flagged_incomplete(self):
        line = self.Line.create({'search_id': self.search.id, 'source': 'google', 'name': 'Google Bar'})
        self.assertFalse(line.partner_incomplete)

    # --- avisos ---

    def test_warning_when_capacity_below_requested_pax(self):
        partner = self.Partner.create(self._complete_vals(restaurant_capacity=30))
        line = self._line(partner)
        self.assertIn('Aforo 30 < 40 pax', line.warnings_text)

    def test_no_capacity_warning_when_capacity_unknown_or_enough(self):
        partner = self.Partner.create(self._complete_vals(restaurant_capacity=0))
        self.assertFalse(self._line(partner, capacity=0).warnings_text)
        partner.restaurant_capacity = 40
        self.assertFalse(self._line(partner, capacity=40).warnings_text)

    def test_warning_when_restaurant_closes_on_event_day(self):
        event = self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': 'Madrid', 'pax': 10, 'event_date': MONDAY,
        })
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 10,
        })
        partner = self.Partner.create(self._complete_vals(restaurant_closed_weekday='mon'))
        line = self._line(partner, search_id=search.id)
        self.assertIn('Cierra los lunes', line.warnings_text)
        event.event_date = TUESDAY
        line.invalidate_recordset()
        self.assertFalse(line.warnings_text)

    def test_closing_day_falls_back_to_lead_service_date(self):
        self.lead.restagrup_service_date = MONDAY
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid', 'min_capacity': 10,
        })
        partner = self.Partner.create(self._complete_vals(restaurant_closed_weekday='mon'))
        self.assertIn('Cierra los lunes', self._line(partner, search_id=search.id).warnings_text)

    # --- pedir datos que faltan (cola de A1) ---

    def _incomplete_line(self, **partner_vals):
        vals = {'name': 'Casa Parcial', 'is_restaurant': True, 'email': 'parcial@example.com',
                'restaurant_capacity': 50, 'restaurant_language': 'es'}
        vals.update(partner_vals)
        return self._line(self.Partner.create(vals))

    def test_request_missing_data_queues_mail_with_only_missing_fields(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        line = self._incomplete_line()
        line.action_request_missing_data()
        mail = self.Pending.search([('line_id', '=', line.id), ('kind', '=', 'data_request')])
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.state, 'pending')
        self.assertEqual(mail.recipient_email, 'parcial@example.com')
        self.assertIn('Día de cierre', mail.body)
        self.assertIn('Responsable de grupos', mail.body)
        self.assertNotIn('Idioma', mail.body)
        self.assertFalse(line.message_ids.filtered(lambda m: m.message_type == 'email'))

    def test_request_missing_data_does_not_duplicate_pending(self):
        line = self._incomplete_line()
        line.action_request_missing_data()
        line.action_request_missing_data()
        self.assertEqual(self.Pending.search_count([('line_id', '=', line.id), ('kind', '=', 'data_request')]), 1)

    def test_request_missing_data_requires_partner_email_and_gaps(self):
        no_email = self._incomplete_line(email=False)
        no_email.email = False
        with self.assertRaises(UserError):
            no_email.action_request_missing_data()
        complete = self._line(self.Partner.create(self._complete_vals(name='Otra Completa')))
        with self.assertRaises(UserError):
            complete.action_request_missing_data()

    def test_approving_data_request_sends_email_on_line_thread(self):
        line = self._incomplete_line()
        line.action_request_missing_data()
        mail = self.Pending.search([('line_id', '=', line.id), ('kind', '=', 'data_request')])
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        self.assertTrue(line.message_ids.filtered(lambda m: m.message_type == 'email'))

    def test_data_request_discarded_if_sheet_completed_while_waiting(self):
        line = self._incomplete_line()
        line.action_request_missing_data()
        mail = self.Pending.search([('line_id', '=', line.id), ('kind', '=', 'data_request')])
        line.partner_id.write({
            'restaurant_closed_weekday': 'mon', 'restaurant_group_manager': 'Ana',
            'restaurant_group_mobile': '611111111',
        })
        mail.action_approve()
        self.assertEqual(mail.state, 'discarded')
        self.assertFalse(line.message_ids.filtered(lambda m: m.message_type == 'email'))

    def test_automatic_mode_sends_data_request_straight_away(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        line = self._incomplete_line()
        line.action_request_missing_data()
        self.assertTrue(line.message_ids.filtered(lambda m: m.message_type == 'email'))

    # --- Google Places rellena sin pisar ---

    def test_adding_google_result_fills_blank_fields_without_overwriting(self):
        existing = self.Partner.create({
            'name': 'Ya Existe', 'is_restaurant': True, 'restaurant_google_place_id': 'PLACE1',
            'phone': '911111111', 'restaurant_cuisine_type': 'Asturiana',
        })
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Ya Existe', 'google_place_id': 'PLACE1',
            'phone': '922222222', 'address': 'Calle Nueva 1', 'cuisine_type': 'Otra',
            'rating': 4.5, 'review_count': 100,
        })
        line.action_add_as_partner()
        self.assertEqual(line.partner_id, existing)
        self.assertEqual(existing.phone, '911111111')
        self.assertEqual(existing.restaurant_cuisine_type, 'Asturiana')
        self.assertEqual(existing.street, 'Calle Nueva 1')
        self.assertEqual(self.Partner.search_count([('restaurant_google_place_id', '=', 'PLACE1')]), 1)
