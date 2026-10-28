# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_sanitize

_logger = logging.getLogger(__name__)

SEND_MODES = ('approval', 'automatic')
DEFAULT_SEND_MODE = 'approval'


class RestagrupPendingMail(models.Model):
    """Cola de correos que genera el sistema y que una persona debe aprobar antes de que salgan.

    Los envíos que dispara una persona con un botón no pasan por aquí: el clic ya es la aprobación."""
    _name = 'restagrup.pending.mail'
    _inherit = ['mail.thread']
    _description = 'Correo pendiente de aprobar'
    _order = 'id desc'
    _rec_name = 'subject'

    kind = fields.Selection(
        [('quote_reminder', 'Recordatorio a restaurante'), ('data_request', 'Petición de datos de ficha'),
         ('lead_data_request', 'Petición de datos a la agencia')], string='Tipo', required=True, readonly=True,
    )
    state = fields.Selection(
        [('pending', 'Pendiente'), ('sent', 'Enviado'), ('discarded', 'Descartado'), ('error', 'Error')],
        string='Estado', default='pending', required=True, readonly=True, index=True,
    )
    line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Restaurante', ondelete='cascade', readonly=True, index=True,
    )
    request_lead_id = fields.Many2one(
        'crm.lead', string='Petición de la agencia', ondelete='cascade', readonly=True, index=True,
        help='Grupo al que se piden los datos que faltan (solo en las peticiones de datos a la agencia).',
    )
    search_id = fields.Many2one(related='line_id.search_id', string='Búsqueda', store=True)
    lead_id = fields.Many2one(related='line_id.search_id.lead_id', string='Grupo', store=True)
    group_id = fields.Many2one(
        'crm.lead', string='Grupo', compute='_compute_group_id',
        help='La petición de la agencia de la que trata este correo.',
    )
    recipient_email = fields.Char(string='Destinatario')
    subject = fields.Char(string='Asunto', required=True)
    body = fields.Text(string='Mensaje', required=True)
    reason = fields.Char(string='Motivo', readonly=True)
    approved_by = fields.Many2one('res.users', string='Aprobado por', readonly=True)
    approved_date = fields.Datetime(string='Fecha de aprobación', readonly=True)
    error_message = fields.Char(string='Error', readonly=True)

    @api.depends('lead_id', 'request_lead_id')
    def _compute_group_id(self):
        for mail in self:
            mail.group_id = mail.request_lead_id or mail.lead_id

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

    @api.model
    def _enqueue_data_request(self, line):
        """Deja en la cola la petición de datos de la ficha. No duplica mientras haya una pendiente."""
        line.ensure_one()
        if self.search_count([('line_id', '=', line.id), ('kind', '=', 'data_request'), ('state', '=', 'pending')]):
            return self.browse()
        subject, body = line._data_request_content(self.env.user.name)
        return self.create({
            'kind': 'data_request', 'line_id': line.id, 'recipient_email': line._get_quote_email_to(),
            'subject': subject, 'body': body,
            'reason': _('Faltan datos: %s') % line.missing_fields_text,
        })

    @api.model
    def _enqueue_lead_data_request(self, lead, email_to, subject, body, missing):
        """Deja en la cola la petición de datos a la agencia. No duplica mientras haya una esperando."""
        lead.ensure_one()
        if self.search_count([('request_lead_id', '=', lead.id), ('kind', '=', 'lead_data_request'),
                              ('state', '=', 'pending')]):
            return self.browse()
        mail = self.create({
            'kind': 'lead_data_request', 'request_lead_id': lead.id, 'recipient_email': email_to,
            'subject': subject, 'body': body, 'reason': _('Faltan datos: %s') % '; '.join(missing),
        })
        mail._post_original_request(missing)
        return mail

    def _original_request_email(self):
        """(remitente, fecha, cuerpo saneado) del correo con el que llegó la petición. Recién llegado aún no está en
        el lead y viene en el contexto; si no, el primer correo guardado del lead. None si se creó a mano."""
        incoming = self.env.context.get('restagrup_incoming_mail')
        if incoming and incoming.get('body'):
            try:
                date = fields.Datetime.to_datetime(incoming.get('date'))
            except (TypeError, ValueError):
                date = False
            return incoming.get('email_from') or '', date, Markup(html_sanitize(incoming['body']))
        first = self.request_lead_id.message_ids.filtered(lambda m: m.message_type == 'email').sorted('id')[:1]
        if not first:
            return None
        return first.email_from or first.author_id.display_name or '', first.date, first.body  # ya saneado

    def _post_original_request(self, missing):
        """Deja en el chatter el correo con el que llegó la petición y lo que la IA echa en falta, para que quien
        aprueba vea por qué se piden datos sin tener que abrir el grupo."""
        self.ensure_one()
        original = self._original_request_email()
        missing_html = Markup('').join(Markup('<li>%s</li>') % item for item in missing)
        if original:
            sender, date, body = original
            when = fields.Datetime.context_timestamp(self, date).strftime('%d/%m/%Y %H:%M') if date else ''
            header = Markup('<p><b>%s</b><br/>%s</p>') % (
                _('Correo original de la petición'), ' · '.join(part for part in (sender, when) if part))
            # Un <div> y no un <blockquote>: el chatter pliega las citas («•••») y el correo tiene que verse entero.
            quoted = Markup('<div style="border-left: 3px solid #ccc; padding-left: 10px; margin: 6px 0;">%s</div>') % body
        else:
            header = Markup('<p><b>%s</b></p>') % _('La petición no tiene correo original (se creó a mano).')
            quoted = Markup('')
        self.message_post(
            body=header + quoted + Markup('<p><b>%s</b> %s</p><ul>%s</ul>') % (
                _('Por qué se piden datos:'),
                _('para buscar restaurante cada servicio necesita ciudad, fecha y número de comensales'
                  ' (el aforo y la disponibilidad dependen del día), y en el correo falta:'),
                missing_html),
            subtype_xmlid='mail.mt_note',
        )

    def _still_applies_lead_data_request(self):
        lead = self.request_lead_id
        return bool(lead.active and lead._restagrup_missing_request_data())

    def _send_lead_data_request(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.request_lead_id._restagrup_send_data_request(
            self.subject, self.body, self.recipient_email, attachments=self._approx_attachments())

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

    def _still_applies_data_request(self):
        return self.line_id.partner_id.restaurant_is_incomplete

    def _send_data_request(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        line = self.line_id
        line._post_email(self.subject, self.body, self.recipient_email)
        line._mark_data_requested()
        line.search_id.message_post_if_exists(_('Petición de datos a %(name)s aprobada por %(user)s.') % {
            'name': line.name, 'user': self.env.user.name,
        })

    def _send_quote_reminder(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        line = self.line_id
        line._post_quote_reminder(self.subject, self.body, self.recipient_email)
        line.search_id.message_post_if_exists(_('Recordatorio a %(name)s aprobado por %(user)s.') % {
            'name': line.name, 'user': self.env.user.name,
        })
