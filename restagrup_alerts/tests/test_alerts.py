# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAlerts(TransactionCase):
    """Avisos con icono: cada usuario ve los tipos a los que está suscrito (o todos), y además, si así se configura,
    lo que es suyo como comercial."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Center = cls.env['restagrup.alert.center']
        cls.Sub = cls.env['restagrup.alert.subscription']
        cls.Pending = cls.env['restagrup.pending.mail']
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.alerts_notify_owner', 'True')
        # Lo que ya hubiera en la base no debe contar: los tests miran solo sus propios registros.
        cls.env['restagrup.pending.mail'].search([('state', '=', 'pending')]).write({'state': 'discarded'})
        cls.env['crm.lead'].search([('restagrup_unseen', '=', True)]).write({'restagrup_unseen': False})
        cls.env['restagrup.restaurant.search.line'].search(
            [('etiqueta', '=', 'solicitado'), ('quote_amount', '!=', 0)]).write({'quote_amount': 0})
        # Como los comerciales reales: ven todas las peticiones.
        group_user = cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.ana = cls.env['res.users'].create({'name': 'Ana Avisos', 'login': 'ana_avisos', 'group_ids': [(4, group_user.id)]})
        cls.bea = cls.env['res.users'].create({'name': 'Bea Avisos', 'login': 'bea_avisos', 'group_ids': [(4, group_user.id)]})
        cls.carla = cls.env['res.users'].create({'name': 'Carla Avisos', 'login': 'carla_avisos', 'group_ids': [(4, group_user.id)]})

    def _lead_with_pending(self, owner):
        lead = self.env['crm.lead'].create({
            'name': 'Grupo %s' % owner.name, 'email_from': 'agencia@example.com', 'user_id': owner.id})
        self.env['restagrup.lead.event'].create({'lead_id': lead.id, 'city': 'Sevilla', 'pax': 40})
        lead._restagrup_ask_for_missing_data()
        return lead, self.Pending.search([('request_lead_id', '=', lead.id)])

    def _search(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo búsqueda', 'user_id': self.ana.id})
        return self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'user_id': self.ana.id})

    def _alerts(self, user):
        return {alert['kind']: alert for alert in self.Center.with_user(user).get_alerts()}

    # --- quién ve qué ---

    def test_owner_sees_only_their_own_pending_mails(self):
        self._lead_with_pending(self.ana)
        self._lead_with_pending(self.bea)
        alerts = self._alerts(self.ana)
        self.assertEqual(alerts['pending_approval']['count'], 1)
        self.assertEqual(set(alerts), {'pending_approval'})

    def test_user_without_subscription_and_without_records_sees_nothing(self):
        self._lead_with_pending(self.ana)
        self.assertEqual(self._alerts(self.carla), {})

    def test_subscription_to_a_kind_shows_every_record_of_that_kind(self):
        self._lead_with_pending(self.ana)
        self._lead_with_pending(self.bea)
        self.Sub.create({'user_id': self.carla.id, 'pending_approval': True})
        alerts = self._alerts(self.carla)
        self.assertEqual(alerts['pending_approval']['count'], 2)

    def test_receive_all_covers_every_kind(self):
        lead, _pending = self._lead_with_pending(self.ana)
        lead.restagrup_unseen = True
        self.Sub.create({'user_id': self.carla.id, 'receive_all': True})
        alerts = self._alerts(self.carla)
        self.assertEqual(set(alerts), {'pending_approval', 'new_request'})

    def test_owner_alerts_can_be_switched_off(self):
        self._lead_with_pending(self.ana)
        self.env['ir.config_parameter'].sudo().set_param('restagrup.alerts_notify_owner', 'False')
        self.assertEqual(self._alerts(self.ana), {})

    def test_one_subscription_per_user(self):
        self.Sub.create({'user_id': self.carla.id})
        with self.assertRaises(Exception), self.cr.savepoint():
            self.Sub.create({'user_id': self.carla.id})

    # --- cada tipo ---

    def test_sent_pending_mail_no_longer_alerts(self):
        _lead, pending = self._lead_with_pending(self.ana)
        pending.action_approve()
        self.assertNotIn('pending_approval', self._alerts(self.ana))

    def test_new_request_from_email_is_unseen_until_someone_opens_it(self):
        with patch('odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
                   return_value=({'eventos': []}, 'groq')):
            lead = self.env['crm.lead'].with_context(mail_create_nolog=True).message_new({
                'subject': 'Petición grupo', 'email_from': 'agencia@example.com', 'body': '<p>Hola</p>',
                'from': 'agencia@example.com', 'to': 'peticiones@example.com'})
        self.assertTrue(lead.restagrup_unseen)
        lead.user_id = self.ana
        self.assertEqual(self._alerts(self.ana)['new_request']['count'], 1)
        lead.with_user(self.bea).web_read({'name': {}})
        self.assertFalse(lead.restagrup_unseen)
        self.assertNotIn('new_request', self._alerts(self.ana))

    def test_leads_created_by_hand_are_not_new_requests(self):
        lead = self.env['crm.lead'].create({'name': 'A mano', 'user_id': self.ana.id})
        self.assertFalse(lead.restagrup_unseen)

    def test_quote_proposed_by_ai_alerts_until_confirmed(self):
        search = self._search()
        partner = self.env['res.partner'].create({'name': 'Rest Aviso', 'is_restaurant': True})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'name': 'Rest Aviso', 'partner_id': partner.id, 'source': 'partner', 'etiqueta': 'solicitado'})
        self.assertNotIn('quote_to_confirm', self._alerts(self.ana))
        line.quote_amount = 900.0
        self.assertEqual(self._alerts(self.ana)['quote_to_confirm']['count'], 1)
        line.etiqueta = 'presupuesto_recibido'
        self.assertNotIn('quote_to_confirm', self._alerts(self.ana))

    def test_client_choice_alerts_until_a_sale_order_exists(self):
        search = self._search()
        partner = self.env['res.partner'].create({'name': 'Rest Elegido', 'is_restaurant': True})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'name': 'Rest Elegido', 'partner_id': partner.id, 'source': 'partner',
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 800.0})
        line._choose_line()
        self.assertNotIn('client_choice', self._alerts(self.ana), 'si elige una persona del equipo, no avisa')
        search._restagrup_mark_client_choice()
        self.assertEqual(self._alerts(self.ana)['client_choice']['count'], 1)
        search.sale_order_id = self.env['sale.order'].create({'partner_id': partner.id})
        self.assertNotIn('client_choice', self._alerts(self.ana))

    # --- lo que devuelve cada aviso ---

    def test_alert_carries_icon_title_and_an_action_with_exactly_those_records(self):
        _lead, pending = self._lead_with_pending(self.ana)
        alert = self._alerts(self.ana)['pending_approval']
        self.assertTrue(alert['icon'].startswith('fa-'))
        self.assertIn('1', alert['title'])
        self.assertEqual(alert['action']['res_model'], 'restagrup.pending.mail')
        self.assertEqual(self.Pending.search(alert['action']['domain']), pending)

    def test_title_uses_plural_when_needed(self):
        self._lead_with_pending(self.ana)
        self._lead_with_pending(self.ana)
        self.assertIn('2 correos', self._alerts(self.ana)['pending_approval']['title'])

    # --- en tiempo real ---

    def test_new_pending_mail_pings_owner_and_subscribers(self):
        self.Sub.create({'user_id': self.carla.id, 'pending_approval': True})
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            self._lead_with_pending(self.ana)
        pinged = {call.args[0] for call in sendone.call_args_list if call.args[1] == 'restagrup_alerts_refresh'}
        self.assertIn(self.ana.partner_id, pinged)
        self.assertIn(self.carla.partner_id, pinged)
        self.assertNotIn(self.bea.partner_id, pinged)
