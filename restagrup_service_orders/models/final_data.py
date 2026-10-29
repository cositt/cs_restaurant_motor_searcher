# -*- coding: utf-8 -*-
"""Datos definitivos de cada evento (menú, intolerancias, guía, comensales): aviso interno y petición a la agencia
cuando se acerca la fecha."""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

FINAL_DATA_DAYS_PARAM = 'restagrup.final_data_days'
DEFAULT_FINAL_DATA_DAYS = 7
REMINDER_SUMMARY = 'Datos pendientes antes del servicio'


class RestagrupLeadEventFinalData(models.Model):
    _inherit = 'restagrup.lead.event'

    guide_contact = fields.Char(string='Contacto del guía')
    intolerances = fields.Text(string='Intolerancias / alergias')
    no_intolerances = fields.Boolean(
        string='Sin intolerancias', help='La agencia ha confirmado que no hay intolerancias ni alergias.')
    pax_final = fields.Boolean(
        string='Comensales definitivos', help='El número de comensales ya es el definitivo.')
    final_missing = fields.Char(string='Datos por cerrar', compute='_compute_final_missing')

    @api.depends(
        'guide_contact', 'intolerances', 'no_intolerances', 'pax_final', 'search_ids.chosen_line_id.menu_id',
        'search_ids.sale_order_id.order_line.restaurant_id',
    )
    def _compute_final_missing(self):
        for event in self:
            missing = []
            menu_defined = event.search_ids.chosen_line_id.menu_id or any(
                line.restaurant_id for line in event.search_ids.sale_order_id.order_line)
            if not menu_defined:
                missing.append(_('Menú definitivo'))
            if not (event.intolerances or event.no_intolerances):
                missing.append(_('Intolerancias'))
            if not event.guide_contact:
                missing.append(_('Contacto del guía'))
            if not event.pax_final:
                missing.append(_('Comensales definitivos'))
            event.final_missing = ', '.join(missing)

    @api.model
    def _final_data_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(FINAL_DATA_DAYS_PARAM)
        try:
            return int(raw) if raw else DEFAULT_FINAL_DATA_DAYS
        except ValueError:
            return DEFAULT_FINAL_DATA_DAYS

    @api.model
    def _reminder_note_posted(self, lead):
        return bool(lead.message_ids.filtered(lambda m: REMINDER_SUMMARY in (m.body or '')))

    @api.model
    def _cron_final_data_reminders(self):
        """Cron diario: avisa internamente (actividad + aviso) de los eventos de un expediente que se acercan y aún
        tienen datos por cerrar. No escribe a nadie de fuera: solo avisa al responsable. Una vez por grupo mientras
        el aviso siga abierto."""
        today = fields.Date.context_today(self)
        close = self.search([
            ('event_date', '>=', today), ('event_date', '<=', today + timedelta(days=self._final_data_days())),
            ('lead_id.stage_id.restagrup_stage_key', '=', 'expediente'),
        ])
        for lead in close.lead_id:
            try:
                with self.env.cr.savepoint():
                    lead._restagrup_ask_final_data()
            except Exception:  # noqa: BLE001 -- un grupo roto no debe parar al resto
                _logger.exception('Petición de datos pendientes a la agencia fallida para %s', lead.name)
        events = close.filtered('final_missing')
        for lead in events.lead_id:
            already = self.env['mail.activity'].sudo().search_count([
                ('res_model', '=', 'crm.lead'), ('res_id', '=', lead.id), ('summary', '=', REMINDER_SUMMARY)])
            if already or self._reminder_note_posted(lead):
                continue
            lines = ['%s: %s' % (event.display_name, event.final_missing)
                     for event in events.filtered(lambda e: e.lead_id == lead)]
            try:
                with self.env.cr.savepoint():
                    notified = self.env['restagrup.ai.log']._notify(
                        lead, REMINDER_SUMMARY, '<br/>'.join(lines), source=lead)
                    if not notified:  # nadie a quien avisar (ni comercial ni usuario de alertas): que quede a la vista
                        lead.message_post(body=Markup('<b>%s</b><br/>%s') % (REMINDER_SUMMARY, Markup('<br/>').join(
                            Markup.escape(line) for line in lines)))
            except Exception:  # noqa: BLE001 -- un grupo roto no debe parar al resto
                _logger.exception('Aviso de datos pendientes fallido para %s', lead.name)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_final_data_request_date = fields.Datetime(
        string='Datos pendientes pedidos a la agencia', copy=False, readonly=True,
        help='Cuándo se pidió a la agencia lo que falta antes del servicio. Solo se pide una vez por grupo.')

    def _restagrup_final_missing(self):
        """Lo que falta por cerrar antes del servicio, como líneas para el correo a la agencia."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        events = self.restagrup_event_ids.filtered(
            lambda e: e.final_missing and (not e.event_date or e.event_date >= today))
        if len(self.restagrup_event_ids) == 1:
            return [item.strip() for item in events.final_missing.split(',')] if events else []
        return ['%s: %s' % (event.display_name, event.final_missing) for event in events]

    def _restagrup_agency_email(self):
        self.ensure_one()
        orders = self.order_ids.filtered(lambda o: o.state != 'cancel')
        for candidate in (self.partner_id.email, orders[:1].partner_id.email, self.email_from):
            if candidate and candidate.strip():
                return candidate.strip()
        return False

    def _restagrup_final_data_content(self, missing):
        self.ensure_one()
        first = self.restagrup_event_ids.filtered('event_date').sorted('event_date')[:1]
        signer = self.user_id.name or self.env.company.name  # nunca el usuario del cron
        values = {
            'grupo': self.name or '', 'agencia': self.partner_id.name or '',
            'fecha': first.event_date.strftime('%d/%m/%Y') if first else '',
            'faltan': '\n'.join('- %s' % item for item in missing), 'firma': signer,
        }

        def fallback():
            return (_('Datos pendientes — %s') % (self.name or ''),
                    '\n'.join([_('Buenos días,'), '', _('Nos faltaría saber:'), '', values['faltan'], '',
                               _('Gracias!'), signer]))

        return self.env['restagrup.mail.template']._compose('final_data_request', values, fallback)

    def _restagrup_ask_final_data(self):
        """Pide a la agencia lo que falta antes del servicio: por la cola o, si ese tipo sale solo, directamente.
        Una vez por grupo; sin email de la agencia no se pide."""
        self.ensure_one()
        queue = self.env['restagrup.pending.mail']
        if self.restagrup_final_data_request_date or queue.search_count([
                ('request_lead_id', '=', self.id), ('kind', '=', 'final_data_request'), ('state', '!=', 'error')]):
            return False
        missing = self._restagrup_final_missing()
        email_to = self._restagrup_agency_email()
        if not missing or not email_to:
            return False
        subject, body = self._restagrup_final_data_content(missing)
        if queue._is_automatic('final_data_request'):
            self._restagrup_post_final_data_request(subject, body, email_to)
        else:
            queue._enqueue_final_data_request(self, email_to, subject, body, missing)
        return True

    def _restagrup_post_final_data_request(self, subject, body_text, email_to):
        """Por el hilo del grupo: la respuesta de la agencia vuelve al mismo grupo."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(self.user_id.email or self.env.user.email),
            outgoing_email_to=email_to,
        )
        self.restagrup_final_data_request_date = fields.Datetime.now()
