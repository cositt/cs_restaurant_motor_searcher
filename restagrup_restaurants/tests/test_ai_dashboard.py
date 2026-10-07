# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAiDashboard(TransactionCase):
    """A4: tablero sencillo -- correos procesados, % de propuestas confirmadas sin corrección, cola pendiente
    y errores de la semana."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['restagrup.ai.log'].sudo()
        cls.Log.search([]).unlink()
        cls.Dashboard = cls.env['restagrup.ai.dashboard']

    def _log(self, kind='lead_extraction', state='pending', days_ago=0):
        log = self.Log.create({'kind': kind, 'state': state, 'source_label': 'x'})
        if days_ago:
            self.env.cr.execute('UPDATE restagrup_ai_log SET create_date = %s WHERE id = %s',
                                (fields.Datetime.now() - timedelta(days=days_ago), log.id))
            log.invalidate_recordset()
        return log

    def test_empty_dashboard_is_all_zero(self):
        board = self.Dashboard.create({})
        self.assertEqual((board.mails_processed, board.reviewed_count, board.errors_week), (0, 0, 0))
        self.assertEqual(board.confirmed_pct, 0.0)

    def test_processed_mails_counts_each_mail_once_whether_or_not_it_was_classified(self):
        for _i in range(3):
            self._log('lead_extraction')
        self.assertEqual(self.Dashboard.create({}).mails_processed, 3)  # clasificación apagada: solo extracciones
        for _i in range(5):
            self._log('mail_classification', 'auto')
        self.assertEqual(self.Dashboard.create({}).mails_processed, 5)  # con clasificación, cada correo una vez

    def test_confirmed_percentage_counts_only_human_reviews(self):
        self._log('quote_extraction', 'confirmed')
        self._log('quote_extraction', 'confirmed')
        self._log('quote_extraction', 'confirmed')
        self._log('quote_extraction', 'corrected')
        self._log('data_extraction', 'pending')    # sin revisar: no cuenta
        self._log('mail_classification', 'auto')   # sin revisión: no cuenta
        board = self.Dashboard.create({})
        self.assertEqual(board.reviewed_count, 4)
        self.assertEqual(board.confirmed_pct, 75.0)

    def test_discarded_counts_as_not_accepted(self):
        self._log('data_extraction', 'confirmed')
        self._log('data_extraction', 'discarded')
        self.assertEqual(self.Dashboard.create({}).confirmed_pct, 50.0)

    def test_only_the_last_seven_days_count(self):
        self._log('lead_extraction', 'error', days_ago=10)
        self._log('lead_extraction', 'error', days_ago=2)
        self._log('quote_extraction', 'confirmed', days_ago=20)
        board = self.Dashboard.create({})
        self.assertEqual(board.errors_week, 1)
        self.assertEqual(board.reviewed_count, 0)
        self.assertEqual(board.mails_processed, 2 - 1)  # la extracción de hace 10 días queda fuera

    def test_pending_queue_counts_mails_waiting_for_approval(self):
        before = self.Dashboard.create({}).pending_queue
        lead = self.env['crm.lead'].create({'name': 'Grupo cola A4'})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 5})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'google', 'name': 'R', 'email': 'r@example.com'})
        self.env['restagrup.pending.mail'].create({
            'kind': 'quote_reminder', 'line_id': line.id, 'recipient_email': 'r@example.com',
            'subject': 's', 'body': 'b'})
        self.assertEqual(self.Dashboard.create({}).pending_queue, before + 1)

    def test_dashboard_has_a_readable_name(self):
        self.assertEqual(self.Dashboard.create({}).display_name, 'Actividad IA')

    def test_open_dashboard_returns_a_form_on_a_fresh_record(self):
        action = self.Dashboard.open_dashboard()
        self.assertEqual(action['res_model'], 'restagrup.ai.dashboard')
        self.assertTrue(action['res_id'])

    def test_drill_down_actions_filter_the_log(self):
        board = self.Dashboard.create({})
        self.assertIn(('state', '=', 'error'), board.action_view_errors()['domain'])
        self.assertIn(('state', 'in', ['confirmed', 'corrected', 'discarded']), board.action_view_reviewed()['domain'])

    def test_a_normal_user_can_open_the_dashboard_and_the_log(self):
        user = self.env['res.users'].create({
            'name': 'Normal A4d', 'login': 'normal_a4d', 'email': 'n4d@example.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        self._log('lead_extraction', 'error')
        board = self.env['restagrup.ai.dashboard'].with_user(user).create({})
        self.assertEqual(board.errors_week, 1)
        self.env['restagrup.ai.log'].with_user(user).search([]).read(['name', 'state'])
