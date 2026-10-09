# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFinalData(TransactionCase):
    """Datos definitivos de cada evento (menú, intolerancias, guía, comensales) y aviso cuando se acerca la fecha."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Responsable datos', 'login': 'resp_datos', 'email': 'resp@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.alert_user_id', str(cls.user.id))
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.final_data_days', '7')
        cls.restaurant = cls.env['res.partner'].create({'name': 'Casa datos', 'is_restaurant': True})
        cls.stage_expediente = cls.env['crm.stage'].search([('restagrup_stage_key', '=', 'expediente')], limit=1)

    def _event(self, days_ahead=3, stage=True, **vals):
        lead = self.env['crm.lead'].create({'name': 'Grupo datos %s' % days_ahead, 'user_id': self.user.id})
        if stage:
            lead.stage_id = self.stage_expediente
        base = {
            'lead_id': lead.id, 'city': 'Sevilla', 'pax': 40,
            'event_date': fields.Date.context_today(lead) + timedelta(days=days_ahead),
            'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id,
        }
        return self.env['restagrup.lead.event'].create({**base, **vals})

    def _with_menu(self, event):
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú definitivo', 'partner_id': self.restaurant.id,
            'currency_id': self.env.company.currency_id.id, 'season': fields.Date.context_today(event).year,
        })
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': event.lead_id.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 10})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Casa datos', 'partner_id': self.restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 20.0, 'menu_id': menu.id})
        line.action_toggle_chosen()

    # --- qué falta ---

    def test_new_event_misses_the_four_final_data(self):
        missing = self._event().final_missing
        for label in ('Menú definitivo', 'Intolerancias', 'Contacto del guía', 'Comensales definitivos'):
            self.assertIn(label, missing)

    def test_each_datum_filled_removes_its_label(self):
        event = self._event()
        event.guide_contact = 'Pedro 600111222'
        self.assertNotIn('Contacto del guía', event.final_missing)
        event.intolerances = 'Dos celíacos'
        self.assertNotIn('Intolerancias', event.final_missing)
        event.pax_final = True
        self.assertNotIn('Comensales definitivos', event.final_missing)

    def test_confirming_there_are_no_intolerances_counts_as_filled(self):
        event = self._event()
        event.no_intolerances = True
        self.assertNotIn('Intolerancias', event.final_missing)

    def test_chosen_restaurant_menu_counts_as_final_menu(self):
        event = self._event()
        self._with_menu(event)
        self.assertNotIn('Menú definitivo', event.final_missing)

    def test_menu_in_the_sale_order_counts_as_final_menu(self):
        event = self._event()
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': event.lead_id.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 10})
        product = self.env['product.template'].create({
            'name': 'Menú de producto', 'type': 'service', 'standard_price': 25.0, 'sale_ok': True,
            'restaurant_id': self.restaurant.id}).product_variant_id
        order = self.env['sale.order'].create({
            'partner_id': self.restaurant.id, 'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 40})]})
        search.sudo().sale_order_id = order
        self.assertNotIn('Menú definitivo', event.final_missing)

    def test_complete_event_has_nothing_missing(self):
        event = self._event(guide_contact='Pedro', intolerances='Ninguna conocida', pax_final=True)
        self._with_menu(event)
        self.assertFalse(event.final_missing)

    # --- aviso cuando se acerca la fecha ---

    def _activities(self, lead):
        return self.env['mail.activity'].search([('res_model', '=', 'crm.lead'), ('res_id', '=', lead.id)])

    def test_cron_warns_when_the_service_is_close_and_data_is_missing(self):
        event = self._event(days_ahead=3)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        activities = self._activities(event.lead_id)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, self.user)
        self.assertIn('Contacto del guía', activities.note)

    def test_cron_does_not_repeat_the_warning(self):
        event = self._event(days_ahead=3)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertEqual(len(self._activities(event.lead_id)), 1)

    def test_cron_ignores_far_past_complete_and_not_yet_expediente(self):
        far = self._event(days_ahead=30)
        past = self._event(days_ahead=-2)
        complete = self._event(days_ahead=3, guide_contact='Pedro', intolerances='Ninguna', pax_final=True)
        self._with_menu(complete)
        early = self._event(days_ahead=3, stage=False)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        for event in (far, past, complete, early):
            self.assertFalse(self._activities(event.lead_id), event.lead_id.name)

    def test_cron_threshold_comes_from_settings(self):
        event = self._event(days_ahead=10)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertFalse(self._activities(event.lead_id))
        self.env['ir.config_parameter'].sudo().set_param('restagrup.final_data_days', '14')
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertTrue(self._activities(event.lead_id))
