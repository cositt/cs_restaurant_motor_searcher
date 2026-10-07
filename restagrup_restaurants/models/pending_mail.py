# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SEND_MODES = ('approval', 'automatic')
DEFAULT_SEND_MODE = 'approval'


class RestagrupPendingMail(models.Model):
    """Cola de correos que genera el sistema y que una persona debe aprobar antes de que salgan.

    Los envíos que dispara una persona con un botón no pasan por aquí: el clic ya es la aprobación."""
    _name = 'restagrup.pending.mail'
    _description = 'Correo pendiente de aprobar'
    _order = 'id desc'
    _rec_name = 'subject'

    kind = fields.Selection(
        [('quote_reminder', 'Recordatorio a restaurante')], string='Tipo', required=True, readonly=True,
    )
    state = fields.Selection(
        [('pending', 'Pendiente'), ('sent', 'Enviado'), ('discarded', 'Descartado'), ('error', 'Error')],
        string='Estado', default='pending', required=True, readonly=True, index=True,
    )
    line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Restaurante', ondelete='cascade', readonly=True, index=True,
    )
    search_id = fields.Many2one(related='line_id.search_id', string='Búsqueda', store=True)
    lead_id = fields.Many2one(related='line_id.search_id.lead_id', string='Grupo', store=True)
    recipient_email = fields.Char(string='Destinatario')
    subject = fields.Char(string='Asunto', required=True)
    body = fields.Text(string='Mensaje', required=True)
    reason = fields.Char(string='Motivo', readonly=True)
    approved_by = fields.Many2one('res.users', string='Aprobado por', readonly=True)
    approved_date = fields.Datetime(string='Fecha de aprobación', readonly=True)
    error_message = fields.Char(string='Error', readonly=True)

    @api.model
    def _send_mode(self):
        """'approval' (por defecto) o 'automatic'. Cualquier otro valor cuenta como 'approval': ante la
        duda no sale nada sin aprobar."""
        mode = self.env['ir.config_parameter'].sudo().get_param('restagrup.send_mode')
        return mode if mode in SEND_MODES else DEFAULT_SEND_MODE

    @api.model
    def _enqueue_quote_reminder(self, line):
        """Deja el recordatorio de la línea en la cola. No duplica: si ya hubo uno (pendiente, enviado o
        descartado) no se vuelve a crear, así un descarte no se repite cada día."""
        line.ensure_one()
        if self.search_count([('line_id', '=', line.id), ('kind', '=', 'quote_reminder'),
                              ('state', '!=', 'error')]):
            return self.browse()
        email_to = line._get_quote_email_to()
        signer = line.search_id.user_id.name or self.env.company.name  # nunca el usuario del cron
        subject, body = line._quote_reminder_content(signer)
        return self.create({
            'kind': 'quote_reminder', 'line_id': line.id, 'recipient_email': email_to,
            'subject': subject, 'body': body,
            'reason': _('Sin respuesta tras %s días') % line.quote_days_pending,
        })

    def action_approve(self):
        """Envía los correos pendientes. Un fallo en uno queda anotado y no para al resto."""
        for mail in self.filtered(lambda m: m.state == 'pending'):
            if not mail._still_applies():
                # El restaurante ya contestó (o ya se le recordó) mientras esperaba aprobación.
                mail.write({'state': 'discarded', 'error_message': _('Ya no procede: la petición ha cambiado.')})
                continue
            try:
                with self.env.cr.savepoint():
                    mail._send()
            except Exception as exc:  # noqa: BLE001 -- un correo roto no debe bloquear la aprobación en lote
                _logger.exception('Correo pendiente %s no enviado', mail.id)
                mail.write({'state': 'error', 'error_message': str(exc)[:250]})
        return True

    def action_discard(self):
        self.filtered(lambda m: m.state == 'pending').write({'state': 'discarded'})
        return True

    def _still_applies(self):
        self.ensure_one()
        return getattr(self, '_still_applies_%s' % self.kind)()

    def _send(self):
        self.ensure_one()
        getattr(self, '_send_%s' % self.kind)()
        self.write({'state': 'sent', 'approved_by': self.env.user.id, 'approved_date': fields.Datetime.now()})

    def _still_applies_quote_reminder(self):
        line = self.line_id
        return line.etiqueta == 'solicitado' and not line.quote_reminder_sent_date

    def _send_quote_reminder(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        line = self.line_id
        line._post_quote_reminder(self.subject, self.body, self.recipient_email)
        line.search_id.message_post_if_exists(_('Recordatorio a %(name)s aprobado por %(user)s.') % {
            'name': line.name, 'user': self.env.user.name,
        })
