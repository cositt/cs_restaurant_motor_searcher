# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.exceptions import AccessError
from odoo.fields import Datetime
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPendingMail(TransactionCase):
    """A1: durante la fase inicial ningún correo que genere el sistema sale sin que una persona lo
    apruebe. El cron deja el recordatorio en la cola y solo sale al aprobarlo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo de prueba'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 20,
        })
        cls.Line = cls.env['restagrup.restaurant.search.line']
        cls.Pending = cls.env['restagrup.pending.mail']

    def _stale_line(self, **vals):
        defaults = {
            'search_id': self.search.id, 'source': 'google', 'name': 'Restaurante Colgado',
            'etiqueta': 'solicitado', 'email': 'chef@example.com',
            'quote_requested_date': Datetime.now() - timedelta(days=5),
        }
        defaults.update(vals)
        return self.Line.create(defaults)

    def _emails(self, line):
        return line.message_ids.filtered(lambda m: m.message_type == 'email')

    def _set_mode(self, mode):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', mode)

    def _queue_one(self, **vals):
        line = self._stale_line(**vals)
        self.Line._cron_send_quote_reminders()
        return line, self.Pending.search([('line_id', '=', line.id)])

    # --- modo de envíos ---

    def test_default_mode_is_approval(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.send_mode')]).unlink()
        self.assertEqual(self.Pending._send_mode(), 'approval')

    def test_unknown_mode_falls_back_to_approval(self):
        self._set_mode('loquesea')
        self.assertEqual(self.Pending._send_mode(), 'approval')

    # --- el cron ---

    def test_cron_queues_instead_of_sending_in_approval_mode(self):
        line, pending = self._queue_one()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending.state, 'pending')
        self.assertEqual(pending.kind, 'quote_reminder')
        self.assertEqual(pending.recipient_email, 'chef@example.com')
        self.assertTrue(pending.subject)
        self.assertTrue(pending.body)
        self.assertEqual(pending.search_id, self.search)
        self.assertEqual(pending.lead_id, self.lead)
        self.assertFalse(self._emails(line))
        self.assertFalse(line.quote_reminder_sent_date)

    def test_cron_does_not_queue_twice(self):
        line, pending = self._queue_one()
        self.Line._cron_send_quote_reminders()
        self.assertEqual(self.Pending.search_count([('line_id', '=', line.id)]), 1)

    def test_cron_does_not_requeue_a_discarded_reminder(self):
        line, pending = self._queue_one()
        pending.action_discard()
        self.Line._cron_send_quote_reminders()
        self.assertEqual(self.Pending.search_count([('line_id', '=', line.id)]), 1)
        self.assertFalse(self._emails(line))

    def test_cron_skips_recent_and_answered_lines(self):
        recent = self._stale_line(name='Reciente', quote_requested_date=Datetime.now())
        answered = self._stale_line(name='Recibido', etiqueta='presupuesto_recibido')
        self.Line._cron_send_quote_reminders()
        self.assertFalse(self.Pending.search([('line_id', 'in', (recent | answered).ids)]))

    def test_cron_skips_line_without_email_and_keeps_going(self):
        no_email = self._stale_line(name='Sin email', email=False)
        ok = self._stale_line(name='Con email')
        self.Line._cron_send_quote_reminders()
        self.assertFalse(self.Pending.search([('line_id', '=', no_email.id)]))
        self.assertEqual(self.Pending.search_count([('line_id', '=', ok.id)]), 1)

    def test_automatic_mode_sends_directly_without_queue(self):
        self._set_mode('automatic')
        line = self._stale_line()
        self.Line._cron_send_quote_reminders()
        self.assertEqual(len(self._emails(line)), 1)
        self.assertFalse(self.Pending.search([('line_id', '=', line.id)]))

    def test_queued_text_is_signed_by_the_search_owner_or_the_company(self):
        owner = self.env['res.users'].create({'name': 'Responsable Firma', 'login': 'firma_cola_test'})
        self.search.user_id = owner
        line, pending = self._queue_one()
        self.assertEqual(pending.body.splitlines()[-1], 'Responsable Firma')
        self.search.user_id = False
        other, pending2 = self._queue_one(name='Otro')
        self.assertEqual(pending2.body.splitlines()[-1], self.env.company.name)

    def test_display_name_is_the_subject(self):
        line, pending = self._queue_one()
        self.assertEqual(pending.display_name, pending.subject)

    # --- aprobar / descartar ---

    def test_approve_sends_the_email_and_records_who_and_when(self):
        line, pending = self._queue_one()
        pending.action_approve()
        self.assertEqual(pending.state, 'sent')
        self.assertEqual(pending.approved_by, self.env.user)
        self.assertTrue(pending.approved_date)
        self.assertEqual(len(self._emails(line)), 1)
        self.assertTrue(line.quote_reminder_sent_date)
        self.assertIn('chef@example.com', self._emails(line).outgoing_email_to)

    def test_approve_sends_the_edited_subject_and_body(self):
        line, pending = self._queue_one()
        pending.write({'subject': 'Asunto corregido', 'body': 'Texto corregido a mano'})
        pending.action_approve()
        message = self._emails(line)
        self.assertEqual(message.subject, 'Asunto corregido')
        self.assertIn('Texto corregido a mano', message.body)

    def test_approve_twice_sends_once(self):
        line, pending = self._queue_one()
        pending.action_approve()
        pending.action_approve()
        self.assertEqual(len(self._emails(line)), 1)

    def test_approve_many_at_once(self):
        a, pa = self._queue_one()
        b = self._stale_line(name='Otro colgado')
        self.Line._cron_send_quote_reminders()
        (self.Pending.search([('line_id', 'in', (a | b).ids)])).action_approve()
        self.assertEqual(len(self._emails(a)), 1)
        self.assertEqual(len(self._emails(b)), 1)

    def test_approve_does_not_send_if_restaurant_already_answered(self):
        line, pending = self._queue_one()
        line.etiqueta = 'presupuesto_recibido'
        pending.action_approve()
        self.assertEqual(pending.state, 'discarded')
        self.assertFalse(self._emails(line))

    def test_discard_sends_nothing(self):
        line, pending = self._queue_one()
        pending.action_discard()
        self.assertEqual(pending.state, 'discarded')
        self.assertFalse(self._emails(line))
        self.assertFalse(line.quote_reminder_sent_date)

    def test_failure_is_recorded_and_does_not_stop_the_rest(self):
        a, pa = self._queue_one()
        b = self._stale_line(name='Bueno')
        self.Line._cron_send_quote_reminders()
        pb = self.Pending.search([('line_id', '=', b.id)])
        pa.recipient_email = False
        (pa | pb).action_approve()
        self.assertEqual(pa.state, 'error')
        self.assertTrue(pa.error_message)
        self.assertEqual(pb.state, 'sent')

    def test_approval_leaves_a_note_in_the_search_chatter(self):
        line, pending = self._queue_one()
        pending.action_approve()
        notes = ' '.join(self.search.message_ids.mapped('body'))
        self.assertIn(self.env.user.name, notes)

    # --- permisos ---

    def test_salesman_can_approve(self):
        salesman = self.env['res.users'].create({
            'name': 'Comercial Cola', 'login': 'comercial_cola_test', 'email': 'cola@restagrup.test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        line, pending = self._queue_one()
        for op in ('read', 'write', 'create'):
            self.assertTrue(self.Pending.with_user(salesman).has_access(op))
        pending.with_user(salesman).action_approve()
        self.assertEqual(pending.state, 'sent')
        self.assertEqual(pending.approved_by, salesman)

    def test_nobody_can_delete_the_history(self):
        line, pending = self._queue_one()
        user = self.env['res.users'].create({
            'name': 'Otro', 'login': 'otro_cola_test', 'email': 'otro@restagrup.test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            pending.with_user(user).unlink()
