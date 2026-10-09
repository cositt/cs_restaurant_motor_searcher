# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestAiLog(TransactionCase):
    """A4: cada acción de la IA queda registrada con su origen, lo que propuso y cómo terminó."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['restagrup.ai.log']
        cls.connector = cls.env['restagrup.llm.connector']
        cls.owner = cls.env['res.users'].create({'name': 'Responsable A4', 'login': 'resp_a4', 'email': 'r4@example.test'})
        cls.alert_user = cls.env['res.users'].create({'name': 'Alertas A4', 'login': 'alert_a4', 'email': 'al4@example.test'})
        cls.source = cls.env['res.partner'].create({'name': 'Origen A4', 'user_id': cls.owner.id})
        cls.orphan = cls.env['res.partner'].create({'name': 'Sin responsable A4'})
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.alert_user_id')]).unlink()

    def _run(self, data, provider='groq', source=None, review=True, text='Hola, somos 30.'):
        with patch(LLM_PATH, return_value=(data, provider)):
            return self.connector.run('lead_extraction', 'prompt', text, source=source or self.source,
                                      label='Asunto de prueba', review=review)

    # --- registro ---

    def test_run_returns_the_ai_answer_and_a_pending_log(self):
        data, provider, log = self._run({'ciudad': 'Madrid'})
        self.assertEqual(data, {'ciudad': 'Madrid'})
        self.assertEqual(provider, 'groq')
        self.assertEqual(log.state, 'pending')
        self.assertEqual(log.kind, 'lead_extraction')
        self.assertEqual(log.provider, 'groq')
        self.assertTrue(log.model_name)
        self.assertEqual(json.loads(log.output), {'ciudad': 'Madrid'})
        self.assertEqual(log.source_label, 'Asunto de prueba')
        self.assertEqual((log.source_model, log.source_res_id), ('res.partner', self.source.id))

    def test_input_excerpt_is_truncated(self):
        _d, _p, log = self._run({'a': 1}, text='x' * 5000)
        self.assertLessEqual(len(log.input_excerpt), 801)

    def test_review_false_logs_as_automatic(self):
        _d, _p, log = self._run({'a': 1}, review=False)
        self.assertEqual(log.state, 'auto')

    def test_unlinked_log_without_source_is_fine(self):
        with patch(LLM_PATH, return_value=({'a': 1}, 'groq')):
            _d, _p, log = self.connector.run('mail_classification', 'p', 'texto', label='Correo')
        self.assertFalse(log.source_model)

    # --- errores y alertas ---

    def test_failure_is_logged_as_error_and_alerts_the_responsible(self):
        data, provider, log = self._run(None, provider=None)
        self.assertIsNone(data)
        self.assertEqual(log.state, 'error')
        self.assertTrue(log.error_message)
        self.assertEqual(log.activity_ids.user_id, self.owner)
        self.assertIn('IA', log.activity_ids.summary)

    def test_failure_without_responsible_uses_the_configured_alert_user(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.alert_user_id', str(self.alert_user.id))
        _d, _p, log = self._run(None, provider=None, source=self.orphan)
        self.assertEqual(log.activity_ids.user_id, self.alert_user)

    def test_failure_with_nobody_to_alert_still_logs(self):
        _d, _p, log = self._run(None, provider=None, source=self.orphan)
        self.assertEqual(log.state, 'error')
        self.assertFalse(log.activity_ids)

    def test_automatic_success_creates_no_error_activity(self):
        _d, _p, log = self._run({'a': 1}, review=False)
        self.assertFalse(log.activity_ids)

    # --- cierre ---

    def test_resolve_closes_the_latest_pending_log_of_that_source_and_kind(self):
        _d, _p, old = self._run({'a': 1})
        _d, _p, new = self._run({'a': 2})
        self.Log._resolve('lead_extraction', self.source, 'corrected')
        self.assertEqual(new.state, 'corrected')
        self.assertEqual(new.reviewed_by, self.env.user)
        self.assertTrue(new.reviewed_date)
        self.assertEqual(old.state, 'pending')

    def test_resolve_ignores_other_kinds_sources_and_closed_logs(self):
        _d, _p, log = self._run({'a': 1})
        self.Log._resolve('quote_extraction', self.source, 'confirmed')
        self.Log._resolve('lead_extraction', self.orphan, 'confirmed')
        self.assertEqual(log.state, 'pending')
        self.Log._resolve('lead_extraction', self.source, 'confirmed')
        self.Log._resolve('lead_extraction', self.source, 'corrected')
        self.assertEqual(log.state, 'confirmed')

    # --- permisos ---

    def test_normal_users_can_read_but_not_edit_the_log(self):
        _d, _p, log = self._run({'a': 1})
        user = self.env['res.users'].create({
            'name': 'Normal A4', 'login': 'normal_a4', 'email': 'n4@example.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        log.with_user(user).read(['state'])
        with self.assertRaises(AccessError):
            log.with_user(user).write({'state': 'confirmed'})
        with self.assertRaises(AccessError):
            log.with_user(user).unlink()

    def test_a_normal_user_triggering_the_ai_still_gets_a_log(self):
        user = self.env['res.users'].create({
            'name': 'Normal2 A4', 'login': 'normal2_a4', 'email': 'n24@example.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with patch(LLM_PATH, return_value=({'a': 1}, 'groq')):
            _d, _p, log = self.env['restagrup.llm.connector'].with_user(user).run(
                'lead_extraction', 'p', 'texto', source=self.source)
        self.assertTrue(log.sudo().exists())


@tagged('post_install', '-at_install')
class TestAiNotifications(TransactionCase):
    """A4: avisos en la UI -- una actividad (contador del reloj) por cada propuesta pendiente de revisar y un
    aviso emergente en tiempo real. Los informativos solo dan el aviso emergente."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['restagrup.ai.log']
        cls.connector = cls.env['restagrup.llm.connector']
        cls.owner = cls.env['res.users'].create({'name': 'Responsable A4n', 'login': 'resp_a4n', 'email': 'r4n@example.test'})
        cls.source = cls.env['res.partner'].create({'name': 'Origen A4n', 'user_id': cls.owner.id})
        cls.orphan = cls.env['res.partner'].create({'name': 'Sin responsable A4n'})
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.alert_user_id')]).unlink()

    def _run(self, kind, data, source=None, review=True, label='Casa Prueba'):
        with patch(LLM_PATH, return_value=(data, 'groq')):
            return self.connector.run(kind, 'prompt', 'texto', source=source or self.source, label=label, review=review)[2]

    def _toasts(self, sendone):
        return [call.args for call in sendone.call_args_list if call.args[1] == 'simple_notification']

    def test_pending_proposal_creates_an_activity_and_a_sticky_toast_for_the_responsible(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            log = self._run('quote_extraction', {'importe': 1200})
        self.assertEqual(log.activity_ids.user_id, self.owner)
        self.assertIn('Casa Prueba', log.activity_ids.summary)
        self.assertIn('1200', log.activity_ids.summary)
        toasts = self._toasts(sendone)
        self.assertEqual(len(toasts), 1)
        target, _type, payload = toasts[0]
        self.assertEqual(target, self.owner.partner_id)
        self.assertTrue(payload['sticky'])
        self.assertIn('Casa Prueba', payload['message'] + payload['title'])

    def test_closing_the_review_removes_the_activity(self):
        log = self._run('data_extraction', {'responsable': 'Marta'})
        self.assertTrue(log.activity_ids)
        log._close('confirmed')
        self.assertFalse(log.activity_ids)

    def test_informational_sheet_reply_toasts_without_an_activity(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            log = self._run('sheet_classification', {'estado': 'accepted', 'resumen': 'Todo bien'}, review=False)
        self.assertFalse(log.activity_ids)
        toasts = self._toasts(sendone)
        self.assertEqual(len(toasts), 1)
        self.assertFalse(toasts[0][2]['sticky'])

    def test_automatic_classification_of_a_new_request_stays_silent(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            log = self._run('mail_classification', {'categoria': 'new_request'}, review=False)
        self.assertFalse(log.activity_ids)
        self.assertFalse(self._toasts(sendone))

    def test_errors_also_toast_the_responsible(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            self._run('lead_extraction', None)
        self.assertEqual(len(self._toasts(sendone)), 1)

    def test_nobody_to_tell_means_no_activity_and_no_toast_and_no_crash(self):
        with patch.object(type(self.env['bus.bus']), '_sendone') as sendone:
            log = self._run('lead_extraction', {'ciudad': 'Madrid'}, source=self.orphan)
        self.assertEqual(log.state, 'pending')
        self.assertFalse(log.activity_ids)
        self.assertFalse(self._toasts(sendone))

    def test_alert_user_gets_the_notice_when_there_is_no_owner(self):
        alert = self.env['res.users'].create({'name': 'Alertas A4n', 'login': 'alert_a4n', 'email': 'al4n@example.test'})
        self.env['ir.config_parameter'].sudo().set_param('restagrup.alert_user_id', str(alert.id))
        log = self._run('lead_extraction', {'ciudad': 'Madrid'}, source=self.orphan)
        self.assertEqual(log.activity_ids.user_id, alert)

    def test_a_failing_notification_never_breaks_the_ai_pipeline(self):
        with patch.object(type(self.env['bus.bus']), '_sendone', side_effect=RuntimeError('bus caído')):
            log = self._run('quote_extraction', {'importe': 900})
        self.assertEqual(log.state, 'pending')
        self.assertTrue(log.exists())
