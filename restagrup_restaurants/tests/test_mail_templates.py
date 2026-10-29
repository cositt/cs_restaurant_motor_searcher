# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

RESTAURANT_CODES = ('quote_request', 'quote_reminder', 'data_request', 'lead_data_request')


@tagged('post_install', '-at_install')
class TestMailTemplates(TransactionCase):
    """Plantillas de correo: un texto editable por tipo de correo y, por tipo, si sale solo o espera aprobación."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['restagrup.mail.template']
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo plantillas', 'email_from': 'agencia@example.com'})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Ronda', 'pax': 48, 'event_date': date(2027, 3, 14), 'event_time': 14.0,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id,
        })
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Ronda', 'min_capacity': 48})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Rondeño', 'is_restaurant': True, 'email': 'meson@example.com'})

    def _line(self, **vals):
        return self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'partner', 'name': 'Mesón Rondeño',
            'partner_id': self.restaurant.id, **vals})

    def _stale_line(self):
        return self._line(etiqueta='solicitado', quote_requested_date=fields.Datetime.now() - timedelta(days=10))

    def _emails(self, record):
        return record.message_ids.filtered(lambda m: m.message_type == 'email')

    # --- qué plantillas hay ---

    def test_every_generated_mail_has_its_template(self):
        for code in RESTAURANT_CODES:
            template = self.Template._get(code)
            self.assertTrue(template, code)
            self.assertTrue(template.subject and template.body, code)
            self.assertFalse(template.auto_send, '%s: de serie todo espera aprobación' % code)

    def test_one_template_per_code(self):
        with self.assertRaises(Exception), self.cr.savepoint():
            self.Template.create({'code': 'quote_reminder', 'name': 'Otra', 'subject': 'x', 'body': 'y'})

    def test_render_fills_placeholders_and_keeps_unknown_ones(self):
        template = self.Template._get('quote_reminder')
        template.write({'subject': 'Hola {restaurante}', 'body': '{restaurante} · {fecha} · {no_existe}'})
        subject, body = template._render({'restaurante': 'Mesón', 'fecha': '14/03/2027'})
        self.assertEqual(subject, 'Hola Mesón')
        self.assertEqual(body, 'Mesón · 14/03/2027 · {no_existe}')

    def test_templates_list_their_placeholders(self):
        self.assertIn('{restaurante}', self.Template._get('quote_request').placeholders)

    # --- petición de disponibilidad (la manda una persona con el botón) ---

    def test_availability_request_follows_restagrups_format(self):
        line = self._line()
        line.action_request_quote()
        body = self._emails(line).body
        self.assertIn('Consulto disponibilidad', body)
        self.assertIn('14/03/2027', body)
        self.assertIn('48 pax', body)
        self.assertIn('A la espera de tu ok', body)

    def test_availability_request_shows_the_menu_at_the_restaurants_price_never_ours(self):
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú de paso', 'partner_id': self.restaurant.id, 'currency_id': self.env.company.currency_id.id,
            'cost_price': 17.60, 'sale_price': 21.12,
            'line_ids': [(0, 0, {'course': 'entrante', 'name': 'Migas rondeñas'})],
        })
        line = self._line(menu_id=menu.id)
        line.action_request_quote()
        body = self._emails(line).body
        self.assertIn('Migas rondeñas', body)
        self.assertIn('17,60', body)
        self.assertNotIn('21,12', body, 'nuestro precio de venta nunca va al restaurante')

    def test_availability_request_can_never_be_automatic(self):
        template = self.Template._get('quote_request')
        self.assertFalse(template.can_auto_send, 'la manda una persona con el botón: no pasa por la cola')
        with self.assertRaises(Exception), self.cr.savepoint():
            template.auto_send = True

    def test_edited_template_is_what_goes_out(self):
        self.Template._get('quote_request').write({
            'subject': 'Disponibilidad {fecha}', 'body': 'Texto propio para {restaurante}'})
        line = self._line()
        line.action_request_quote()
        message = self._emails(line)
        self.assertEqual(message.subject, 'Disponibilidad 14/03/2027')
        self.assertIn('Texto propio para Mesón Rondeño', message.body)

    # --- automático por tipo ---

    def test_nothing_is_automatic_by_default(self):
        for code in RESTAURANT_CODES:
            self.assertFalse(self.Queue._is_automatic(code), code)

    def test_global_automatic_mode_still_sends_everything(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        self.assertTrue(self.Queue._is_automatic('quote_reminder'))
        self.assertTrue(self.Queue._is_automatic('lead_data_request'))

    def test_automatic_only_for_the_ticked_type(self):
        self.Template._get('quote_reminder').auto_send = True
        self.assertTrue(self.Queue._is_automatic('quote_reminder'))
        self.assertFalse(self.Queue._is_automatic('lead_data_request'))

    def test_automatic_quote_reminder_goes_out_without_queue(self):
        self.Template._get('quote_reminder').auto_send = True
        line = self._stale_line()
        self.env['restagrup.restaurant.search.line']._cron_send_quote_reminders()
        self.assertFalse(self.Queue.search([('line_id', '=', line.id)]))
        self.assertEqual(len(self._emails(line)), 1)
        self.assertTrue(line.quote_reminder_sent_date)

    def test_quote_reminder_waits_for_approval_when_not_ticked(self):
        line = self._stale_line()
        self.env['restagrup.restaurant.search.line']._cron_send_quote_reminders()
        self.assertEqual(len(self.Queue.search([('line_id', '=', line.id), ('state', '=', 'pending')])), 1)
        self.assertFalse(self._emails(line))

    def test_automatic_agency_data_request_goes_out_without_queue(self):
        self.Template._get('lead_data_request').auto_send = True
        lead = self.env['crm.lead'].create({'name': 'Grupo incompleto', 'email_from': 'agencia@example.com'})
        self.env['restagrup.lead.event'].create({'lead_id': lead.id, 'city': 'Sevilla', 'pax': 40})
        lead._restagrup_ask_for_missing_data()
        self.assertFalse(self.Queue.search([('request_lead_id', '=', lead.id)]))
        self.assertEqual(len(self._emails(lead)), 1)

    def test_reminder_uses_the_template_text(self):
        self.Template._get('quote_reminder').body = 'Recordatorio propio para {restaurante}\n\n{firma}'
        line = self._stale_line()
        self.env['restagrup.restaurant.search.line']._cron_send_quote_reminders()
        pending = self.Queue.search([('line_id', '=', line.id)])
        self.assertIn('Recordatorio propio para Mesón Rondeño', pending.body)

    # --- los textos que había en Ajustes pasan a la plantilla ---

    def test_text_from_old_setting_moves_into_the_template_once(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('restagrup.quote_reminder_text', 'Texto antiguo de Ajustes')
        self.Template._import_legacy_texts()
        self.assertIn('Texto antiguo de Ajustes', self.Template._get('quote_reminder').body)
        self.assertIn('{firma}', self.Template._get('quote_reminder').body, 'la firma se seguía añadiendo sola')
        self.assertFalse(params.get_param('restagrup.quote_reminder_text'))

    # --- permisos ---

    def test_team_can_read_templates_and_only_managers_edit_them(self):
        salesman = self.env['res.users'].create({
            'name': 'Comercial plantillas', 'login': 'comercial_plantillas',
            'group_ids': [(6, 0, [self.env.ref('sales_team.group_sale_salesman').id])]})
        manager = self.env['res.users'].create({
            'name': 'Jefa plantillas', 'login': 'jefa_plantillas',
            'group_ids': [(6, 0, [self.env.ref('sales_team.group_sale_manager').id])]})
        self.assertTrue(self.Template.with_user(salesman).has_access('read'))
        self.assertFalse(self.Template.with_user(salesman).has_access('write'))
        self.assertTrue(self.Template.with_user(manager).has_access('write'))
