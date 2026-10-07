# -*- coding: utf-8 -*-
"""A2: seguimiento de presupuestos enviados a la agencia sin respuesta y «Grupo no sale»."""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_REMINDER_DAYS = 14
AGENCY_REMINDER_DEFAULT_TEXT = (
    'Hola,\n\nTe recordamos que el presupuesto %(name)s sigue pendiente de tu respuesta y la fecha del '
    'servicio se acerca. Puedes revisarlo y aceptarlo desde el enlace de abajo; si necesitas algún '
    'cambio, respóndenos a este correo.'
)
# Estados de la petición a un restaurante en los que hay que avisarle si el grupo no sale.
OPEN_REQUEST_STATES = ('solicitado', 'presupuesto_recibido')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    restagrup_service_date = fields.Date(
        string='Fecha de servicio', compute='_compute_restagrup_service_date', store=True,
        help='Fecha del primer servicio del grupo (la más próxima de las líneas).',
    )
    restagrup_days_to_service = fields.Integer(
        string='Días para el servicio', compute='_compute_restagrup_days_to_service',
    )
    restagrup_last_contact = fields.Datetime(
        string='Último contacto', compute='_compute_restagrup_last_contact',
        help='Último correo o comentario en el hilo del presupuesto.',
    )
    restagrup_agency_reminder_date = fields.Datetime(
        string='Recordatorio a la agencia', copy=False, readonly=True,
        help='Cuándo se recordó a la agencia que el presupuesto sigue sin respuesta. Solo se manda uno.',
    )

    @api.depends('order_line.service_date')
    def _compute_restagrup_service_date(self):
        for order in self:
            dates = [d for d in order.order_line.mapped('service_date') if d]
            order.restagrup_service_date = min(dates) if dates else False

    @api.depends('restagrup_service_date')
    def _compute_restagrup_days_to_service(self):
        today = fields.Date.context_today(self)
        for order in self:
            order.restagrup_days_to_service = (
                (order.restagrup_service_date - today).days if order.restagrup_service_date else 0
            )

    @api.depends('message_ids.date', 'message_ids.message_type')
    def _compute_restagrup_last_contact(self):
        for order in self:
            dates = order.message_ids.filtered(lambda m: m.message_type in ('email', 'comment')).mapped('date')
            order.restagrup_last_contact = max(dates) if dates else False

    # --- recordatorio a la agencia ---

    @api.model
    def _agency_reminder_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param('restagrup.agency_reminder_days')
        try:
            return int(value) if value else DEFAULT_REMINDER_DAYS
        except ValueError:
            return DEFAULT_REMINDER_DAYS

    def _agency_reminder_content(self, signer_name):
        """Asunto y texto (con enlace al portal y firma) del recordatorio de un presupuesto sin respuesta."""
        self.ensure_one()
        subject = _('Recordatorio: presupuesto %s pendiente') % self.name
        text = self.env['ir.config_parameter'].sudo().get_param('restagrup.agency_reminder_text')
        text = text or AGENCY_REMINDER_DEFAULT_TEXT % {'name': self.name}
        link = self.get_base_url() + self._get_share_url(redirect=True)
        return subject, '\n'.join(text.splitlines() + ['', link, '', signer_name])

    def _post_agency_reminder(self, subject, body_text, email_to):
        """Envía el recordatorio por el hilo del presupuesto y anota la fecha: solo se manda uno."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject,
            message_type='email',
            subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(self.user_id.email or self.env.user.email),
            outgoing_email_to=email_to,
        )
        self.write({'restagrup_agency_reminder_date': fields.Datetime.now()})

    @api.model
    def _cron_agency_reminders(self):
        """Cron diario: presupuestos enviados cuyo servicio está dentro del umbral y aún sin recordatorio.
        Con envíos «con aprobación» (por defecto) el recordatorio queda en la cola; en automático sale."""
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=self._agency_reminder_days())
        orders = self.search([
            ('state', '=', 'sent'),
            ('restagrup_service_date', '>=', today),
            ('restagrup_service_date', '<=', limit),
            ('restagrup_agency_reminder_date', '=', False),
        ])
        queue = self.env['restagrup.pending.mail']
        automatic = queue._send_mode() == 'automatic'
        for order in orders:
            email_to = (order.partner_id.email or '').strip()
            if not email_to:
                _logger.warning('Presupuesto %s sin email de agencia: no se le recuerda.', order.name)
                continue
            try:
                with self.env.cr.savepoint():
                    signer = order.user_id.name or self.env.company.name
                    if automatic:
                        subject, body = order._agency_reminder_content(signer)
                        order._post_agency_reminder(subject, body, email_to)
                    else:
                        queue._enqueue_agency_reminder(order, email_to, signer)
            except Exception:  # noqa: BLE001 -- un presupuesto roto no debe parar al resto
                _logger.exception('Recordatorio de agencia fallido para %s', order.name)

    # --- Grupo no sale ---

    def action_group_not_going(self):
        """El grupo no sale: cancela el presupuesto, marca el lead como perdido con ese motivo, da por
        canceladas las peticiones a restaurantes y deja en la cola el aviso de cancelación a cada uno."""
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                'Este presupuesto ya está confirmado: cancélalo con el flujo de cambios o cancelaciones '
                'de restaurante, no con «Grupo no sale».'
            ))
        lead = self.opportunity_id
        self.action_cancel()
        if not lead:
            return True
        reason = self.env.ref('restagrup_service_orders.cancel_reason_group_not_going')
        queue = self.env['restagrup.pending.mail']
        lines = lead.restagrup_restaurant_search_ids.line_ids.filtered(lambda l: l.etiqueta in OPEN_REQUEST_STATES)
        for line in lines:
            line.write({
                'etiqueta': 'cancelado', 'cancel_reason_id': reason.id, 'cancelled_date': fields.Datetime.now(),
            })
            if (line.partner_id.email or '').strip():
                queue._enqueue_group_cancelled(line)
            else:
                line.search_id.message_post_if_exists(_(
                    '%s no tiene contacto con email: avísale por otro medio de que el grupo no sale.') % line.name)
        lead.action_set_lost(lost_reason_id=self.env.ref('restagrup_service_orders.lost_reason_group_not_going').id)
        return True

