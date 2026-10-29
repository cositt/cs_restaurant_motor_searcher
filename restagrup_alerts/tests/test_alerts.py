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
        cls.env['crm.lead'].search([('user_id', '=', False)]).write({'user_id': cls.env.ref('base.user_admin').id})
        cls.env['crm.lead'].search([('restagrup_assigned_unseen', '=', True)]).write({'restagrup_assigned_unseen': False})
        cls.env['sale.order'].search([('restagrup_payment_proof_state', '!=', False)]).write(
            {'restagrup_payment_proof_state': False})
        cls.env['purchase.order'].search([('restagrup_payment_due', '=', True)]).write({'restagrup_payment_due': False})

    def _lead_with_pending(self, owner):
        lead = self.env['crm.lead'].create({
            'name': 'Grupo %s' % owner.name, 'email_from': 'agencia@example.com', 'user_id': owner.id,
            'restagrup_assigned_unseen': False})  # aquí no se prueba la asignación
        self.env['restagrup.lead.event'].create({'lead_id': lead.id, 'city': 'Sevilla', 'pax': 40})
        lead._restagrup_ask_for_missing_data()
        return lead, self.Pending.search([('request_lead_id', '=', lead.id)])

    def _search(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo búsqueda', 'user_id': self.ana.id, 'restagrup_assigned_unseen': False})
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
        lead.with_user(self.bea).web_read({'display_name': {}})
        self.assertTrue(lead.restagrup_unseen, 'leer solo su nombre (desde otro registro) no es abrirla')
        lead.with_user(self.bea).web_read({'name': {}, 'restagrup_unseen': {}})
        self.assertFalse(lead.restagrup_unseen, 'abrir la ficha sí')
        self.assertNotIn('new_request', self._alerts(self.ana))

    def test_opening_a_record_linked_to_the_request_does_not_mark_it_seen(self):
        lead, pending = self._lead_with_pending(self.ana)
        lead.restagrup_unseen = True
        pending.with_user(self.ana).web_read({'request_lead_id': {'fields': {'display_name': {}}}})
        self.assertTrue(lead.restagrup_unseen)

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

    # --- asignación ---

    def _unassigned_request(self):
        stage = self.env.ref('restagrup_service_orders.stage_peticion')
        return self.env['crm.lead'].create({'name': 'Grupo libre', 'user_id': False, 'stage_id': stage.id})

    def test_unassigned_requests_alert_only_subscribers(self):
        self._unassigned_request()
        self.assertNotIn('unassigned', self._alerts(self.ana), 'no es de nadie: solo lo ve quien reparte')
        self.Sub.create({'user_id': self.carla.id, 'unassigned': True})
        alert = self._alerts(self.carla)['unassigned']
        self.assertEqual(alert['count'], 1)
        self.assertIn('sin asignar', alert['title'])

    def test_unassigned_alert_ignores_closed_and_lost_groups(self):
        self.Sub.create({'user_id': self.carla.id, 'unassigned': True})
        closed = self._unassigned_request()
        closed.stage_id = self.env.ref('restagrup_service_orders.stage_cerrado')
        self._unassigned_request().action_archive()
        self.assertNotIn('unassigned', self._alerts(self.carla))

    def test_assigning_someone_else_alerts_the_assignee_until_they_open_it(self):
        lead = self._unassigned_request()
        lead.with_user(self.carla).write({'user_id': self.ana.id})
        alert = self._alerts(self.ana)['assigned']
        self.assertEqual(alert['count'], 1)
        self.assertIn('asignada', alert['title'])
        self.assertNotIn('assigned', self._alerts(self.carla), 'el aviso es solo para quien la recibe')
        lead.with_user(self.bea).web_read({'name': {}, 'restagrup_unseen': {}})
        self.assertIn('assigned', self._alerts(self.ana), 'que la abra otro no cuenta')
        lead.with_user(self.ana).web_read({'name': {}, 'restagrup_unseen': {}})
        self.assertNotIn('assigned', self._alerts(self.ana))

    def test_assigned_alert_does_not_depend_on_owner_setting_nor_on_receive_all(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.alerts_notify_owner', 'False')
        self.Sub.create({'user_id': self.carla.id, 'receive_all': True})
        lead = self._unassigned_request()
        lead.with_user(self.bea).write({'user_id': self.ana.id})
        self.assertIn('assigned', self._alerts(self.ana))
        self.assertNotIn('assigned', self._alerts(self.carla), '«Todos» no incluye lo asignado a otros')

    def test_taking_a_request_yourself_does_not_alert(self):
        lead = self._unassigned_request()
        lead.with_user(self.ana).write({'user_id': self.ana.id})
        self.assertNotIn('assigned', self._alerts(self.ana))

    def test_reassigning_moves_the_alert_to_the_new_responsible(self):
        lead = self._unassigned_request()
        lead.with_user(self.carla).write({'user_id': self.ana.id})
        lead.with_user(self.carla).write({'user_id': self.bea.id})
        self.assertNotIn('assigned', self._alerts(self.ana))
        self.assertIn('assigned', self._alerts(self.bea))

    def test_assignment_pings_the_assignee_and_who_distributes_work(self):
        self.Sub.create({'user_id': self.carla.id, 'unassigned': True})
        lead = self._unassigned_request()
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            lead.with_user(self.carla).write({'user_id': self.ana.id})
        pinged = {(call.args[0], call.args[2]['kind']) for call in sendone.call_args_list
                  if call.args[1] == 'restagrup_alerts_refresh'}
        self.assertIn((self.ana.partner_id, 'assigned'), pinged)
        self.assertIn((self.carla.partner_id, 'unassigned'), pinged)

    def test_request_alerts_open_the_groups_list_not_the_crm_one(self):
        self.Sub.create({'user_id': self.carla.id, 'unassigned': True})
        self._unassigned_request()
        views = self._alerts(self.carla)['unassigned']['action']['views']
        self.assertEqual(views[0], [self.env.ref('restagrup_service_orders.view_crm_lead_restagrup_list').id, 'list'])

    # --- justificantes de pago ---

    def _confirmed_order(self, owner):
        agency = self.env['res.partner'].create({'name': 'Agencia avisos', 'email': 'ag-avisos@example.com'})
        order = self.env['sale.order'].create({
            'partner_id': agency.id, 'user_id': owner.id,
            'order_line': [(0, 0, {'product_id': self.env['product.product'].create({
                'name': 'Menú avisos', 'type': 'service', 'list_price': 20.0}).id, 'product_uom_qty': 10})]})
        order.action_confirm()
        return order

    def test_payment_receipt_alerts_its_owner_until_confirmed(self):
        order = self._confirmed_order(self.ana)
        order.restagrup_payment_proof_state = 'received'
        alert = self._alerts(self.ana)['payment_proof']
        self.assertEqual(alert['action']['domain'], [('id', 'in', order.ids)])
        self.assertNotIn('payment_proof', self._alerts(self.bea))
        self.Sub.create({'user_id': self.carla.id, 'payment_proof': True})
        self.assertIn('payment_proof', self._alerts(self.carla), 'administración puede suscribirse')
        order.action_confirm_payment_proof()
        self.assertNotIn('payment_proof', self._alerts(self.ana))

    def test_payment_receipt_pings_the_owner(self):
        order = self._confirmed_order(self.ana)
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            order.restagrup_payment_proof_state = 'received'
        self.assertIn(self.ana.partner_id, {call.args[0] for call in sendone.call_args_list})

    def test_pending_mail_of_an_order_alerts_the_order_owner(self):
        order = self._confirmed_order(self.ana)
        self.Pending.create({'kind': 'agency_payment_request', 'sale_order_id': order.id,
                             'recipient_email': 'ag-avisos@example.com', 'subject': 'Pago', 'body': 'Pago'})
        self.assertIn('pending_approval', self._alerts(self.ana))

    # --- pagos a restaurantes ---

    def _restaurant_sheet(self, owner):
        restaurant = self.env['res.partner'].create({'name': 'Casa avisos', 'is_restaurant': True, 'email': 'c@example.com'})
        product = self.env['product.template'].create({
            'name': 'Menú casa avisos', 'type': 'service', 'standard_price': 10.0, 'sale_ok': True,
            'restaurant_id': restaurant.id}).product_variant_id
        order = self.env['sale.order'].create({
            'partner_id': restaurant.id, 'user_id': owner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 10})]})
        order.action_confirm()
        return order.restaurant_po_ids

    def test_restaurant_payment_due_alerts_the_group_owner_and_subscribers(self):
        purchase = self.env.ref('purchase.group_purchase_user')
        (self.ana | self.bea | self.carla).write({'group_ids': [(4, purchase.id)]})  # quien paga ve las hojas
        sheet = self._restaurant_sheet(self.ana)
        sheet.sudo().restagrup_payment_due = True
        self.assertIn('restaurant_payment', self._alerts(self.ana))
        self.assertNotIn('restaurant_payment', self._alerts(self.bea))
        self.Sub.create({'user_id': self.carla.id, 'restaurant_payment': True})
        self.assertIn('restaurant_payment', self._alerts(self.carla))
        sheet.sudo().action_mark_restaurant_paid()
        self.assertNotIn('restaurant_payment', self._alerts(self.ana))

    def test_pending_mail_of_a_sheet_alerts_the_group_owner(self):
        sheet = self._restaurant_sheet(self.ana)
        self.Pending.create({'kind': 'restaurant_bank_request', 'purchase_order_id': sheet.id,
                             'recipient_email': 'c@example.com', 'subject': 'Cuenta', 'body': 'Cuenta'})
        self.assertIn('pending_approval', self._alerts(self.ana))
