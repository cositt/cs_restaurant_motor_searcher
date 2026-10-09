# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRestaurantNotices(TransactionCase):
    """Aviso conjunto a varios restaurantes de un grupo (p. ej. +1 comensal) y seguimiento de sus
    respuestas. Solo restaurantes: la agencia no recibe nada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))  # sin puntos de revisión
        cls.client = cls.env['res.partner'].create({'name': 'Agencia avisos', 'email': 'ag@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo avisos', 'partner_id': cls.client.id})
        cls.rest_a = cls.env['res.partner'].create({
            'name': 'Casa Málaga', 'is_restaurant': True, 'email': 'a@example.com'})
        cls.rest_b = cls.env['res.partner'].create({
            'name': 'Casa Sevilla', 'is_restaurant': True, 'email': 'b@example.com'})
        cls.rest_c = cls.env['res.partner'].create({'name': 'Casa Sin Email', 'is_restaurant': True})
        cls.ev_a = cls._event('Málaga', 'restagrup_core.event_type_lunch', '2026-11-15', 42, cls.rest_a, 1000)
        cls.ev_b = cls._event('Sevilla', 'restagrup_core.event_type_dinner', '2026-11-16', 40, cls.rest_b, 800)
        cls.order = cls.ev_a.search_ids.sale_order_id

    @classmethod
    def _event(cls, city, type_xmlid, date, pax, restaurant, amount):
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': city, 'pax': pax, 'event_date': date,
            'event_type_id': cls.env.ref(type_xmlid).id,
        })
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': city, 'min_capacity': pax,
        })
        line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name,
            'partner_id': restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': amount,
        })
        line.action_toggle_chosen()
        search.action_create_sale_order()
        return event

    def _wizard(self, **vals):
        wizard = self.lead._create_notice_wizard()
        if vals:
            wizard.write(vals)
        return wizard

    def _send(self, subject='Cambio', body='<p>Hola {restaurante}</p>', **kw):
        wizard = self._wizard(subject=subject, body=body)
        wizard.action_send()
        return self.env['restagrup.restaurant.notice'].search([('lead_id', '=', self.lead.id)])

    # --- a quién se avisa ---

    def test_wizard_lists_the_chosen_restaurant_of_every_event(self):
        wizard = self._wizard()
        self.assertEqual(wizard.line_ids.mapped('restaurant_id'), self.rest_a | self.rest_b)
        labels = ' '.join(wizard.line_ids.mapped('event_label'))
        self.assertIn('Málaga', labels)
        self.assertIn('Sevilla', labels)

    def test_restaurant_without_email_is_flagged_and_not_selected(self):
        self._event('Toledo', 'restagrup_core.event_type_dinner', '2026-11-17', 30, self.rest_c, 500)
        line = self._wizard().line_ids.filtered(lambda l: l.restaurant_id == self.rest_c)
        self.assertFalse(line.has_email)
        self.assertFalse(line.selected)

    def test_only_selected_restaurants_are_notified(self):
        wizard = self._wizard(subject='Aviso', body='<p>Hola</p>')
        wizard.line_ids.filtered(lambda l: l.restaurant_id == self.rest_b).selected = False
        wizard.action_send()
        notices = self.env['restagrup.restaurant.notice'].search([('lead_id', '=', self.lead.id)])
        self.assertEqual(notices.mapped('restaurant_id'), self.rest_a)

    # --- por qué hilo sale el aviso ---

    def test_notice_goes_through_the_quote_thread_when_there_is_no_service_sheet(self):
        notices = self._send(subject='Aviso sin hoja')
        self.assertEqual(set(notices.mapped('thread_model')), {LINE})
        line = self.ev_a.search_ids.chosen_line_id
        self.assertIn('Aviso sin hoja', ' '.join(m.subject or '' for m in line.message_ids))

    def test_notice_goes_through_the_service_sheet_when_it_exists(self):
        self.order.action_confirm()
        notices = self._send(subject='Aviso con hoja')
        self.assertEqual(set(notices.mapped('thread_model')), {'purchase.order'})
        sheet = self.order.restaurant_po_ids.filtered(lambda po: po.partner_id == self.rest_a)
        self.assertIn('Aviso con hoja', ' '.join(m.subject or '' for m in sheet.message_ids))

    def test_notices_start_pending_with_their_message_and_sender(self):
        notice = self._send().filtered(lambda n: n.restaurant_id == self.rest_a)
        self.assertEqual(notice.state, 'pending')
        self.assertTrue(notice.mail_message_id)
        self.assertTrue(notice.sent_date)
        self.assertEqual(notice.user_id, self.env.user)

    # --- plantillas, variables y texto libre ---

    def test_placeholders_are_filled_per_restaurant(self):
        notices = self._send(
            subject='Cambio en {evento}',
            body='<p>Hola {restaurante}: {comensales} personas el {fecha} ({grupo}).</p>')
        a = notices.filtered(lambda n: n.restaurant_id == self.rest_a)
        self.assertIn('Casa Málaga', a.body)
        self.assertIn('42 personas', a.body)
        self.assertIn('15/11/2026', a.body)
        self.assertIn('Grupo avisos', a.body)
        self.assertIn('Málaga', a.subject)
        self.assertNotIn('{', a.subject + a.body)

    def test_a_template_fills_subject_and_body_and_can_be_edited(self):
        template = self.env.ref('restagrup_service_orders.notice_template_guests')
        wizard = self._wizard()
        wizard.template_id = template
        wizard._onchange_template_id()
        self.assertEqual(wizard.subject, template.subject)
        wizard.body = '<p>Texto editado {restaurante}</p>'
        wizard.action_send()
        notice = self.env['restagrup.restaurant.notice'].search([('restaurant_id', '=', self.rest_a)])
        self.assertIn('Texto editado', notice.body)

    def test_initial_templates_are_loaded(self):
        names = self.env['restagrup.notice.template'].search([]).mapped('name')
        for name in ('Cambio de comensales', 'Cambio de fecha u hora', 'Aviso general'):
            self.assertIn(name, names)

    def test_notice_needs_subject_and_body(self):
        with self.assertRaises(UserError):
            self._wizard(subject='', body='<p>Algo</p>').action_send()
        with self.assertRaises(UserError):
            self._wizard(subject='Algo', body='<p><br></p>').action_send()

    def test_notice_needs_at_least_one_selected_restaurant(self):
        wizard = self._wizard(subject='Aviso', body='<p>Hola</p>')
        wizard.line_ids.selected = False
        with self.assertRaises(UserError):
            wizard.action_send()

    def test_selected_restaurant_without_email_blocks_the_send(self):
        self._event('Toledo', 'restagrup_core.event_type_dinner', '2026-11-17', 30, self.rest_c, 500)
        wizard = self._wizard(subject='Aviso', body='<p>Hola</p>')
        wizard.line_ids.filtered(lambda l: l.restaurant_id == self.rest_c).selected = True
        with self.assertRaises(UserError):
            wizard.action_send()

    # --- la agencia no interviene ---

    def test_the_agency_receives_nothing(self):
        before = len(self.order.message_ids)
        self._send()
        self.assertEqual(len(self.order.message_ids), before)
        self.assertFalse(self.env['mail.mail'].search([('email_to', 'ilike', 'ag@example.com')]))

    # --- seguimiento de respuestas ---

    def test_reply_on_the_service_sheet_marks_the_notice_replied_with_ai_summary(self):
        self.order.action_confirm()
        notice = self._send().filtered(lambda n: n.restaurant_id == self.rest_a)
        sheet = self.env['purchase.order'].browse(notice.thread_res_id)
        sheet.state = 'sent'
        with patch(LLM, return_value=({'estado': 'accepted', 'resumen': 'Acepta el cambio'}, 'groq')):
            sheet.message_update({'body': '<p>De acuerdo, anotado.</p>', 'parent_id': notice.mail_message_id.id})
        self.assertEqual(notice.state, 'replied')
        self.assertIn('De acuerdo', notice.reply_excerpt)
        self.assertEqual(notice.reply_summary, 'Acepta el cambio')
        self.assertTrue(notice.reply_date)

    def test_reply_on_the_quote_thread_marks_the_notice_replied(self):
        notice = self._send().filtered(lambda n: n.restaurant_id == self.rest_a)
        line = self.env[LINE].browse(notice.thread_res_id)
        with patch(LLM, return_value=(None, None)):
            line.message_update({'body': '<p>Vale, lo apunto.</p>', 'parent_id': notice.mail_message_id.id})
        self.assertEqual(notice.state, 'replied')

    def test_reply_matches_the_notice_it_answers(self):
        first = self._send(subject='Primero').filtered(lambda n: n.restaurant_id == self.rest_a)
        self._wizard(subject='Segundo', body='<p>Hola</p>').action_send()
        second = self.env['restagrup.restaurant.notice'].search([
            ('restaurant_id', '=', self.rest_a), ('subject', '=', 'Segundo')])
        line = self.env[LINE].browse(first.thread_res_id)
        with patch(LLM, return_value=(None, None)):
            line.message_update({'body': '<p>Sobre el primero</p>', 'parent_id': first.mail_message_id.id})
        self.assertEqual(first.state, 'replied')
        self.assertEqual(second.state, 'pending')

    def test_reply_without_a_pending_notice_is_ignored(self):
        line = self.ev_a.search_ids.chosen_line_id
        with patch(LLM, return_value=(None, None)):
            line.message_update({'body': '<p>Hola</p>'})
        self.assertFalse(self.env['restagrup.restaurant.notice'].search([('lead_id', '=', self.lead.id)]))

    # --- resumen del grupo y de cada evento ---

    def test_lead_summary_fields(self):
        self.order.action_confirm()
        self._send()
        self.assertEqual(self.lead.restagrup_event_count, 2)
        self.assertEqual(self.lead.restagrup_order_total, self.order.amount_untaxed)
        self.assertEqual(self.lead.restagrup_confirmation_summary, '0/2')
        self.assertEqual(self.lead.restagrup_notice_pending_count, 2)
        self.assertIn('Casa Málaga', self.lead.restagrup_chosen_summary)
        self.assertIn('Casa Sevilla', self.lead.restagrup_chosen_summary)

    def test_event_shows_its_chosen_restaurant_amount_and_order(self):
        self.assertEqual(self.ev_a.chosen_restaurant_id, self.rest_a)
        self.assertEqual(self.ev_a.chosen_amount, 1000)
        self.assertEqual(self.ev_a.sale_order_id, self.order)

    # --- permisos: un comercial sin Compras ---

    def test_salesperson_without_purchase_rights_can_notify(self):
        self.order.action_confirm()
        user = self.env['res.users'].create({
            'name': 'Comercial avisos', 'login': 'comercial_avisos', 'email': 'com@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id, self.env.ref('sales_team.group_sale_salesman').id])],
        })
        self.lead.user_id = user
        self.order.user_id = user
        wizard = self.lead.with_user(user)._create_notice_wizard()
        wizard.write({'subject': 'Aviso comercial', 'body': '<p>Hola {restaurante}</p>'})
        wizard.action_send()
        self.assertEqual(self.env['restagrup.restaurant.notice'].search_count([('lead_id', '=', self.lead.id)]), 2)
