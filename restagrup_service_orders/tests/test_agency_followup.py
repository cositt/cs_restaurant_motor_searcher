# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgencyFollowup(TransactionCase):
    """A2: presupuestos enviados sin respuesta, recordatorio a la agencia por la cola de A1 y «Grupo no sale»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.Pending = cls.env['restagrup.pending.mail']
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia A2', 'email': 'agencia-a2@example.com'})
        cls.product = cls.env['product.product'].create({'name': 'Menú A2', 'type': 'service'})
        cls.today = fields.Date.context_today(cls.env['sale.order'])

    def _order(self, days=7, state='sent', agency=None, lead=None, dates=None):
        dates = dates if dates is not None else [self.today + timedelta(days=days)]
        order = self.env['sale.order'].create({
            'partner_id': (agency or self.agency).id,
            'opportunity_id': lead.id if lead else False,
            'order_line': [(0, 0, {
                'product_id': self.product.id, 'product_uom_qty': 10, 'price_unit': 20, 'service_date': d,
            }) for d in dates],
        })
        if state == 'sent':
            order.state = 'sent'
        return order

    def _emails(self, record):
        return record.message_ids.filtered(lambda m: m.message_type == 'email')

    def _queued(self, order, kind='agency_reminder'):
        return self.Pending.search([('sale_order_id', '=', order.id), ('kind', '=', kind)])

    # --- fecha de servicio y días ---

    def test_service_date_is_the_earliest_line_date(self):
        order = self._order(dates=[self.today + timedelta(days=9), self.today + timedelta(days=3)])
        self.assertEqual(order.restagrup_service_date, self.today + timedelta(days=3))

    def test_service_date_empty_without_dates_and_follows_edits(self):
        order = self.env['sale.order'].create({'partner_id': self.agency.id})
        self.assertFalse(order.restagrup_service_date)
        order.write({'order_line': [(0, 0, {
            'product_id': self.product.id, 'service_date': self.today + timedelta(days=5)})]})
        self.assertEqual(order.restagrup_service_date, self.today + timedelta(days=5))

    def test_days_to_service(self):
        self.assertEqual(self._order(days=6).restagrup_days_to_service, 6)

    def test_last_contact_is_latest_email_or_comment(self):
        order = self._order()
        self.assertFalse(order.restagrup_last_contact)
        order.message_post(body='hola', message_type='comment', subtype_xmlid='mail.mt_comment')
        self.assertTrue(order.restagrup_last_contact)

    # --- el cron ---

    def test_cron_queues_reminder_for_sent_order_near_service(self):
        order = self._order(days=7)
        self.env['sale.order']._cron_agency_reminders()
        mail = self._queued(order)
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.state, 'pending')
        self.assertEqual(mail.recipient_email, 'agencia-a2@example.com')
        self.assertIn(order.name, mail.subject)
        self.assertIn('access_token=', mail.body)  # enlace al presupuesto con token de acceso
        self.assertFalse(self._emails(order))
        self.assertFalse(order.restagrup_agency_reminder_date)

    def test_cron_skips_what_does_not_apply(self):
        far = self._order(days=40)
        past = self._order(days=-2)
        draft = self._order(days=7, state='draft')
        no_date = self._order(dates=[])
        no_email = self._order(days=7, agency=self.env['res.partner'].create({'name': 'Sin email'}))
        reminded = self._order(days=7)
        reminded.restagrup_agency_reminder_date = fields.Datetime.now()
        self.env['sale.order']._cron_agency_reminders()
        for order in (far, past, draft, no_date, no_email, reminded):
            self.assertFalse(self._queued(order), order.name)

    def test_cron_does_not_duplicate(self):
        order = self._order(days=7)
        self.env['sale.order']._cron_agency_reminders()
        self.env['sale.order']._cron_agency_reminders()
        self.assertEqual(len(self._queued(order)), 1)

    def test_threshold_setting_is_respected(self):
        order = self._order(days=20)
        self.env['sale.order']._cron_agency_reminders()
        self.assertFalse(self._queued(order))
        self.env['ir.config_parameter'].sudo().set_param('restagrup.agency_reminder_days', '30')
        self.env['sale.order']._cron_agency_reminders()
        self.assertEqual(len(self._queued(order)), 1)

    def test_custom_reminder_text_is_used(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.agency_reminder_text', 'Texto propio de prueba')
        order = self._order(days=7)
        self.env['sale.order']._cron_agency_reminders()
        self.assertIn('Texto propio de prueba', self._queued(order).body)

    def test_approving_sends_on_order_thread_and_stamps_date(self):
        order = self._order(days=7)
        self.env['sale.order']._cron_agency_reminders()
        mail = self._queued(order)
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        self.assertEqual(len(self._emails(order)), 1)
        self.assertTrue(order.restagrup_agency_reminder_date)

    def test_approving_is_discarded_if_order_no_longer_waits(self):
        order = self._order(days=7)
        self.env['sale.order']._cron_agency_reminders()
        mail = self._queued(order)
        order.state = 'cancel'
        mail.action_approve()
        self.assertEqual(mail.state, 'discarded')
        self.assertFalse(self._emails(order))

    def test_automatic_mode_sends_straight_away(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        order = self._order(days=7)
        self.env['sale.order']._cron_agency_reminders()
        self.assertFalse(self._queued(order))
        self.assertEqual(len(self._emails(order)), 1)
        self.assertTrue(order.restagrup_agency_reminder_date)

    def test_unanswered_action_lists_sent_orders_by_service_date(self):
        action = self.env.ref('restagrup_service_orders.action_sale_orders_unanswered')
        self.assertEqual(action.res_model, 'sale.order')
        self.assertIn('sent', action.domain)

    # --- Grupo no sale ---

    def _group(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo que no sale'})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 20})
        Line = self.env['restagrup.restaurant.search.line']

        def line(name, etiqueta, email='r@example.com'):
            partner = self.env['res.partner'].create({'name': name, 'is_restaurant': True, 'email': email})
            return Line.create({
                'search_id': search.id, 'source': 'partner', 'name': name, 'partner_id': partner.id,
                'email': email, 'etiqueta': etiqueta})
        lines = {
            'asked': line('Rest Solicitado', 'solicitado'),
            'quoted': line('Rest Presupuesto', 'presupuesto_recibido'),
            'seen': line('Rest Visto', 'visto'),
            'discarded': line('Rest Descartado', 'descartado'),
            'noemail': line('Rest SinEmail', 'solicitado', email=False),
        }
        return lead, lines

    def test_group_not_going_cancels_order_and_loses_lead(self):
        lead, lines = self._group()
        order = self._order(lead=lead)
        order.action_group_not_going()
        self.assertEqual(order.state, 'cancel')
        self.assertFalse(lead.active)
        self.assertEqual(lead.lost_reason_id, self.env.ref('restagrup_service_orders.lost_reason_group_not_going'))

    def test_group_not_going_cancels_requests_and_queues_notices(self):
        lead, lines = self._group()
        order = self._order(lead=lead)
        order.action_group_not_going()
        for key in ('asked', 'quoted', 'noemail'):
            self.assertEqual(lines[key].etiqueta, 'cancelado', key)
            self.assertEqual(lines[key].cancel_reason_id,
                             self.env.ref('restagrup_service_orders.cancel_reason_group_not_going'))
        self.assertEqual(lines['seen'].etiqueta, 'visto')
        self.assertEqual(lines['discarded'].etiqueta, 'descartado')
        queued = self.Pending.search([('kind', '=', 'group_cancelled'), ('line_id', 'in', [l.id for l in lines.values()])])
        self.assertEqual(set(queued.mapped('line_id')), {lines['asked'], lines['quoted']})
        self.assertTrue(all(m.state == 'pending' for m in queued))
        self.assertIn('Rest Solicitado', queued.filtered(lambda m: m.line_id == lines['asked']).body)
        self.assertFalse(self._emails(lines['asked']))

    def test_approving_group_cancelled_sends_notice_and_records_it(self):
        lead, lines = self._group()
        self._order(lead=lead).action_group_not_going()
        mail = self.Pending.search([('kind', '=', 'group_cancelled'), ('line_id', '=', lines['asked'].id)])
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        self.assertTrue(self._emails(lines['asked']))
        self.assertTrue(self.env['restagrup.restaurant.notice'].search([
            ('lead_id', '=', lead.id), ('restaurant_id', '=', lines['asked'].partner_id.id)]))

    def test_group_not_going_removes_order_from_unanswered_list(self):
        lead, lines = self._group()
        order = self._order(lead=lead)
        order.action_group_not_going()
        action = self.env.ref('restagrup_service_orders.action_sale_orders_unanswered')
        self.assertNotIn(order, self.env['sale.order'].search(eval(action.domain)))

    def test_group_not_going_refused_on_confirmed_order(self):
        order = self._order(state='draft')
        order.action_confirm()
        with self.assertRaises(UserError):
            order.action_group_not_going()


@tagged('post_install', '-at_install')
class TestAgencyFollowupPermissions(TransactionCase):
    """Los tests como superusuario no ven permisos: un comercial sin Compras tiene que poder usar «Grupo no
    sale», aprobar los avisos que deja en la cola y abrir la lista de presupuestos sin respuesta."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.salesman = cls.env['res.users'].create({
            'name': 'Comercial A2', 'login': 'comercial_a2', 'email': 'comercial-a2@example.test',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id, cls.env.ref('sales_team.group_sale_salesman').id])],
        })
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia permisos A2', 'email': 'ag@example.test'})
        cls.product = cls.env['product.product'].create({'name': 'Menú perm A2', 'type': 'service'})

    def test_salesman_runs_group_not_going_and_approves_notices(self):
        env = self.env(user=self.salesman)
        lead = env['crm.lead'].create({'name': 'Grupo permisos'})
        search = env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 20})
        restaurant = self.env['res.partner'].create({'name': 'Rest perm', 'is_restaurant': True, 'email': 'r@example.test'})
        line = env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Rest perm',
            'partner_id': restaurant.id, 'etiqueta': 'solicitado'})
        order = env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 5})]})
        order.state = 'sent'
        order.action_group_not_going()
        self.assertEqual(order.state, 'cancel')
        pending = env['restagrup.pending.mail'].search([('line_id', '=', line.id), ('kind', '=', 'group_cancelled')])
        self.assertEqual(len(pending), 1)
        pending.action_approve()
        self.assertEqual(pending.state, 'sent')

    def test_salesman_opens_unanswered_list(self):
        env = self.env(user=self.salesman)
        action = self.env.ref('restagrup_service_orders.action_sale_orders_unanswered')  # lo carga el cliente web
        env['sale.order'].search(eval(action.domain)).read(
            ['name', 'restagrup_service_date', 'restagrup_days_to_service', 'restagrup_last_contact'])
