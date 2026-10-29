# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMailTemplatesFollowup(TransactionCase):
    """Plantillas de los correos a la agencia: presupuesto sin respuesta y datos que faltan antes del servicio."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('restagrup.send_mode', 'approval')
        params.set_param('restagrup.final_data_days', '7')
        cls.Template = cls.env['restagrup.mail.template']
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.user = cls.env['res.users'].create({
            'name': 'Responsable plantillas', 'login': 'resp_plantillas', 'email': 'resp@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])]})
        params.set_param('restagrup.alert_user_id', str(cls.user.id))
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia Plantillas', 'email': 'agencia-p@example.com'})
        cls.product = cls.env['product.product'].create({'name': 'Menú plantillas', 'type': 'service'})
        cls.today = fields.Date.context_today(cls.env['sale.order'])
        cls.expediente = cls.env['crm.stage'].search([('restagrup_stage_key', '=', 'expediente')], limit=1)

    def _emails(self, record):
        return record.message_ids.filtered(lambda m: m.message_type == 'email')

    # --- presupuesto sin respuesta ---

    def _sent_order(self, days=7):
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'user_id': self.user.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 10, 'price_unit': 20,
                                   'service_date': self.today + timedelta(days=days)})],
        })
        order.state = 'sent'
        return order

    def test_agency_reminder_has_its_template_with_restagrups_text(self):
        template = self.Template._get('agency_reminder')
        self.assertTrue(template.can_auto_send)
        self.assertIn('no tuvimos respuesta al presupuesto', template.body)

    def test_agency_reminder_renders_link_and_signature(self):
        order = self._sent_order()
        self.env['sale.order']._cron_agency_reminders()
        mail = self.Queue.search([('sale_order_id', '=', order.id), ('kind', '=', 'agency_reminder')])
        self.assertIn('no tuvimos respuesta al presupuesto', mail.body)
        self.assertIn(order.get_base_url() + order._get_share_url(redirect=True), mail.body)
        self.assertIn('Responsable plantillas', mail.body)
        self.assertIn(order.name, mail.subject)

    def test_automatic_agency_reminder_goes_out_without_queue(self):
        self.Template._get('agency_reminder').auto_send = True
        order = self._sent_order()
        self.env['sale.order']._cron_agency_reminders()
        self.assertFalse(self.Queue.search([('sale_order_id', '=', order.id)]))
        self.assertEqual(len(self._emails(order)), 1)

    def test_old_agency_text_setting_moves_into_the_template(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('restagrup.agency_reminder_text', 'Texto antiguo de agencia')
        self.Template._import_legacy_texts()
        body = self.Template._get('agency_reminder').body
        self.assertIn('Texto antiguo de agencia', body)
        self.assertIn('{enlace}', body)
        self.assertFalse(params.get_param('restagrup.agency_reminder_text'))

    # --- datos que faltan antes del servicio (expediente) ---

    def _event(self, days_ahead=3, paid=False, **vals):
        lead = self.env['crm.lead'].create({
            'name': 'Grupo AZM166', 'user_id': self.user.id, 'partner_id': self.agency.id,
            'stage_id': self.expediente.id})
        event = self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'pax': 40,
            'event_date': fields.Date.context_today(lead) + timedelta(days=days_ahead),
            'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id, **vals})
        if paid is not None:
            order = self.env['sale.order'].create({'partner_id': self.agency.id, 'opportunity_id': lead.id})
            order.restagrup_paid = paid
        return event

    def _final_request(self, lead):
        return self.Queue.search([('request_lead_id', '=', lead.id), ('kind', '=', 'final_data_request')])

    def test_final_data_request_has_its_template(self):
        template = self.Template._get('final_data_request')
        self.assertTrue(template.can_auto_send)
        self.assertFalse(template.auto_send)
        self.assertIn('debido a la proximidad de la fecha del servicio', template.body)

    def test_cron_asks_the_agency_for_what_is_missing(self):
        event = self._event()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        mail = self._final_request(event.lead_id)
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.state, 'pending')
        self.assertEqual(mail.recipient_email, 'agencia-p@example.com')
        for label in ('Menú definitivo', 'Intolerancias', 'Contacto del guía', 'Comensales definitivos'):
            self.assertIn(label, mail.body)

    def test_unpaid_group_also_asks_for_the_payment_receipt(self):
        unpaid = self._event(paid=False)
        paid = self._event(paid=True)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertIn('Justificante de pago', self._final_request(unpaid.lead_id).body)
        self.assertNotIn('Justificante de pago', self._final_request(paid.lead_id).body)

    def test_internal_warning_is_kept(self):
        event = self._event()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertTrue(self.env['mail.activity'].search([
            ('res_model', '=', 'crm.lead'), ('res_id', '=', event.lead_id.id)]))

    def test_request_is_not_repeated_while_waiting(self):
        event = self._event()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertEqual(len(self._final_request(event.lead_id)), 1)

    def _choose_menu(self, event):
        partner = self.env['res.partner'].create({'name': 'Casa menú', 'is_restaurant': True})
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú', 'partner_id': partner.id, 'currency_id': self.env.company.currency_id.id})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': event.lead_id.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 10})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Casa menú', 'partner_id': partner.id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 20.0, 'menu_id': menu.id})
        line.action_toggle_chosen()

    def test_nothing_missing_nothing_asked(self):
        event = self._event(paid=True, guide_contact='Pedro 600', no_intolerances=True, pax_final=True)
        self._choose_menu(event)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertFalse(self._final_request(event.lead_id))

    def test_far_or_not_expediente_groups_are_not_asked(self):
        far = self._event(days_ahead=30)
        near = self._event()
        near.lead_id.stage_id = self.env['crm.stage'].search([('restagrup_stage_key', '=', 'presupuesto')], limit=1)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertFalse(self._final_request(far.lead_id))
        self.assertFalse(self._final_request(near.lead_id))

    def test_no_longer_applies_once_the_data_arrives(self):
        event = self._event(paid=True)
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        mail = self._final_request(event.lead_id)
        event.write({'guide_contact': 'Pedro 600', 'no_intolerances': True, 'pax_final': True})
        self.assertTrue(mail._still_applies(), 'falta aún el menú')
        self._choose_menu(event)
        self.assertFalse(mail._still_applies())

    def test_approving_sends_it_on_the_groups_thread(self):
        event = self._event()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        mail = self._final_request(event.lead_id)
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        sent = self._emails(event.lead_id)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent.outgoing_email_to, 'agencia-p@example.com')

    def test_automatic_final_data_request_goes_out_without_queue(self):
        self.Template._get('final_data_request').auto_send = True
        event = self._event()
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertFalse(self._final_request(event.lead_id))
        self.assertEqual(len(self._emails(event.lead_id)), 1)

    def test_group_without_agency_email_is_not_asked(self):
        event = self._event()
        self.agency.email = False
        event.lead_id.email_from = False
        self.env['restagrup.lead.event']._cron_final_data_reminders()
        self.assertFalse(self._final_request(event.lead_id))
