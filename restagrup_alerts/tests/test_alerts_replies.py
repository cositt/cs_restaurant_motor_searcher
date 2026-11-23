# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAlertsReplies(TransactionCase):
    """Ronda 20/11 (4): avisos de que ha contestado un restaurante (a la confirmación de la hoja de servicio) o la
    agencia (al grupo o a su pedido). Cada comercial ve los de sus grupos; se quitan al pulsarlos o al abrir el grupo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.Center = cls.env['restagrup.alert.center']
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.alerts_notify_owner', 'True')
        group = cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.ana = cls.env['res.users'].create({'name': 'Ana Respuestas', 'login': 'ana_resp', 'group_ids': [(4, group.id)]})
        cls.bea = cls.env['res.users'].create({'name': 'Bea Respuestas', 'login': 'bea_resp', 'group_ids': [(4, group.id)]})
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia resp', 'email': 'resp@agencia.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa resp', 'is_restaurant': True, 'email': 'resp@casa.example'})
        cls.outsider = cls.env['res.partner'].create({'name': 'Persona externa', 'email': 'ext@example.com'})
        product = cls.env['product.template'].create({
            'name': 'Menú resp', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0,
            'sale_ok': True, 'restaurant_id': cls.restaurant.id}).product_variant_id
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Grupo respuestas', 'partner_id': cls.agency.id, 'user_id': cls.ana.id,
            'restagrup_assigned_unseen': False, 'restagrup_unseen': False})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.agency.id, 'opportunity_id': cls.lead.id, 'user_id': cls.ana.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_hour': 20.5,
                                   'service_date': fields.Date.context_today(cls.lead) + timedelta(days=20)})]})
        cls.order.action_confirm()
        cls.sheet = cls.order.restaurant_po_ids
        cls.lead.write({'restagrup_restaurant_reply_unseen': False, 'restagrup_agency_reply_unseen': False})

    def _incoming(self, record, author=None):
        return record.message_post(
            body='<p>Todo ok</p>', subject='RE: confirmación', message_type='email',
            subtype_xmlid='mail.mt_comment', author_id=(author or self.outsider).id)

    def _alerts(self, user):
        return {alert['kind']: alert for alert in self.Center.with_user(user).get_alerts()}

    # --- restaurante ---

    def test_restaurant_reply_to_the_sheet_alerts_the_owner(self):
        self._incoming(self.sheet, self.restaurant)
        alert = self._alerts(self.ana)['restaurant_reply']
        self.assertEqual(alert['count'], 1)
        self.assertEqual(alert['action']['res_model'], 'crm.lead')
        self.assertEqual(alert['action']['domain'], [('id', 'in', self.lead.ids)])
        self.assertNotIn('restaurant_reply', self._alerts(self.bea))

    def test_our_own_outgoing_email_does_not_alert(self):
        self._incoming(self.sheet, self.ana.partner_id)
        self.assertNotIn('restaurant_reply', self._alerts(self.ana))

    def test_internal_notes_do_not_alert(self):
        self.sheet.message_post(body='nota', subtype_xmlid='mail.mt_note', author_id=self.outsider.id)
        self.assertNotIn('restaurant_reply', self._alerts(self.ana))

    def test_pressing_the_alert_clears_it_and_a_new_reply_brings_it_back(self):
        self._incoming(self.sheet, self.restaurant)
        self.Center.with_user(self.ana).open_alert('restaurant_reply')
        self.assertNotIn('restaurant_reply', self._alerts(self.ana))
        self._incoming(self.sheet, self.restaurant)
        self.assertIn('restaurant_reply', self._alerts(self.ana))

    def test_opening_the_group_clears_it(self):
        self._incoming(self.sheet, self.restaurant)
        self.lead.with_user(self.ana).web_read({'name': {}, 'restagrup_restaurant_reply_unseen': {}})
        self.assertNotIn('restaurant_reply', self._alerts(self.ana))

    # --- agencia ---

    def test_agency_reply_on_the_group_alerts_the_owner(self):
        self._incoming(self.lead, self.agency)
        alert = self._alerts(self.ana)['agency_reply']
        self.assertEqual(alert['count'], 1)
        self.assertEqual(alert['action']['res_model'], 'crm.lead')
        self.assertNotIn('restaurant_reply', self._alerts(self.ana))

    def test_agency_reply_on_its_order_alerts_the_owner(self):
        self._incoming(self.order, self.agency)
        self.assertEqual(self._alerts(self.ana)['agency_reply']['count'], 1)

    def test_the_first_email_of_a_new_request_is_only_a_new_request(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo nuevo resp', 'user_id': self.ana.id, 'restagrup_unseen': True})
        self._incoming(lead, self.agency)
        self.assertFalse(lead.restagrup_agency_reply_unseen)

    def test_opening_the_group_clears_the_agency_reply(self):
        self._incoming(self.lead, self.agency)
        self.lead.with_user(self.ana).web_read({'name': {}, 'restagrup_agency_reply_unseen': {}})
        self.assertNotIn('agency_reply', self._alerts(self.ana))

    # --- suscripción ---

    def test_a_subscriber_sees_every_reply_not_only_their_own(self):
        self.env['restagrup.alert.subscription'].create({
            'user_id': self.bea.id, 'restaurant_reply': True, 'agency_reply': True})
        self._incoming(self.sheet, self.restaurant)
        self._incoming(self.lead, self.agency)
        alerts = self._alerts(self.bea)
        self.assertIn('restaurant_reply', alerts)
        self.assertIn('agency_reply', alerts)
