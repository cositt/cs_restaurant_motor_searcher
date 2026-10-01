# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext


class RestaurantNoticeWizard(models.TransientModel):
    _name = 'restagrup.restaurant.notice.wizard'
    _description = 'Avisar a los restaurantes de un grupo'

    lead_id = fields.Many2one('crm.lead', string='Grupo / Cliente', required=True, readonly=True)
    template_id = fields.Many2one('restagrup.notice.template', string='Plantilla')
    subject = fields.Char(string='Asunto')
    body = fields.Html(string='Texto')
    line_ids = fields.One2many('restagrup.restaurant.notice.wizard.line', 'wizard_id', string='Restaurantes')

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.subject = self.template_id.subject
            self.body = self.template_id.body

    def action_send(self):
        self.ensure_one()
        lines = self.line_ids.filtered('selected')
        if not lines:
            raise UserError(_('Marca al menos un restaurante al que avisar.'))
        if not self.subject or not html2plaintext(self.body or '').strip():
            raise UserError(_('Escribe el asunto y el texto del aviso (o elige una plantilla).'))
        missing = lines.filtered(lambda line: not line.has_email)
        if missing:
            raise UserError(_('Estos restaurantes no tienen email: %s. Añádeselo o desmárcalos.') % ', '.join(
                missing.mapped('restaurant_id.name')))
        if not self.env.user.email:
            raise UserError(_('Tu usuario no tiene email: añádelo antes de enviar avisos.'))
        for line in lines:
            line._send_notice(self.subject, self.body)
        return {'type': 'ir.actions.act_window_close'}


class RestaurantNoticeWizardLine(models.TransientModel):
    _name = 'restagrup.restaurant.notice.wizard.line'
    _description = 'Restaurante a avisar'

    wizard_id = fields.Many2one('restagrup.restaurant.notice.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Avisar', default=True)
    restaurant_id = fields.Many2one('res.partner', string='Restaurante', required=True)
    event_label = fields.Char(string='Evento')
    search_line_id = fields.Many2one('restagrup.restaurant.search.line', string='Resultado de búsqueda')
    po_id = fields.Many2one('purchase.order', string='Hoja de servicio')
    has_email = fields.Boolean(string='Tiene email', compute='_compute_has_email')
    thread_label = fields.Char(string='Sale por', compute='_compute_thread_label')

    @api.depends('restaurant_id.email')
    def _compute_has_email(self):
        for line in self:
            line.has_email = bool((line.restaurant_id.email or '').strip())

    @api.depends('po_id')
    def _compute_thread_label(self):
        for line in self:
            line.thread_label = _('Hoja de servicio') if line.po_id else _('Petición de presupuesto')

    def _placeholder_values(self):
        self.ensure_one()
        search = self.search_line_id.search_id
        event = search.event_id
        return {
            '{restaurante}': self.restaurant_id.name or '',
            '{grupo}': self.wizard_id.lead_id.name or '',
            '{evento}': self.event_label or '',
            '{fecha}': event.event_date.strftime('%d/%m/%Y') if event.event_date else '',
            '{comensales}': str((event.pax or search.min_capacity) or ''),
        }

    def _send_notice(self, subject, body):
        """Envía el aviso por el hilo de la hoja de servicio (o, si aún no hay, por el de la petición de
        presupuesto) para que las respuestas vuelvan enlazadas, y lo deja registrado para el seguimiento."""
        self.ensure_one()
        values = self._placeholder_values()
        rendered_subject, rendered_body = subject, body
        for key, value in values.items():
            rendered_subject = rendered_subject.replace(key, value)
            rendered_body = rendered_body.replace(key, str(escape(value)))
        thread = self.po_id.sudo() if self.po_id else self.search_line_id
        user = self.env.user
        message = thread.message_post(
            body=Markup(rendered_body),
            subject=rendered_subject,
            message_type='email',
            subtype_xmlid='mail.mt_comment',
            author_id=user.partner_id.id,
            email_from=user.email_formatted,
            outgoing_email_to=self.restaurant_id.email.strip(),
        )
        self.env['restagrup.restaurant.notice'].create({
            'lead_id': self.wizard_id.lead_id.id,
            'restaurant_id': self.restaurant_id.id,
            'event_label': self.event_label,
            'subject': rendered_subject,
            'body': rendered_body,
            'thread_model': thread._name,
            'thread_res_id': thread.id,
            'mail_message_id': message.id,
        })
