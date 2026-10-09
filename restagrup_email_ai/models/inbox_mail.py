# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

INBOX_CATEGORIES = [
    ('group_change', 'Cambio de un grupo'),
    ('agency_reply', 'Respuesta de agencia'),
    ('invoice', 'Factura'),
    ('incident', 'Incidencia'),
    ('other', 'Otro'),
]


class RestagrupInboxMail(models.Model):
    """Correo del buzón central que la IA clasificó como algo distinto de una petición nueva y que no se
    pudo enlazar a un grupo existente. No crea nada: queda aquí, etiquetado, para que una persona lo revise."""
    _name = 'restagrup.inbox.mail'
    _description = 'Correo por revisar'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _primary_email = 'email_from'

    name = fields.Char(string='Asunto', required=True)
    email_from = fields.Char(string='Remitente')
    category = fields.Selection(INBOX_CATEGORIES, string='Categoría', required=True, index=True)
    summary = fields.Text(string='Resumen IA')
    state = fields.Selection(
        [('to_review', 'Por revisar'), ('done', 'Revisado')], string='Estado',
        default='to_review', required=True, index=True, tracking=True,
    )
    ai_log_id = fields.Many2one('restagrup.ai.log', string='Registro de la IA', readonly=True, copy=False, ondelete='set null')
    lead_id = fields.Many2one('crm.lead', string='Lead creado', readonly=True, copy=False, ondelete='set null')

    def _original_email(self):
        self.ensure_one()
        emails = self.message_ids.filtered(lambda m: m.message_type == 'email')
        return emails[-1:]

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        item = super().message_new(msg_dict, custom_values=custom_values)
        if item.category == 'incident':
            item._alert_incident(msg_dict)
        return item

    def _alert_incident(self, msg_dict):
        """Una incidencia es lo único que no puede esperar: actividad urgente al responsable del grupo (si se
        reconoce) o al usuario de alertas, y nada más -- el contacto con agencia y restaurante es del equipo."""
        self.ensure_one()
        log = self.env['restagrup.ai.log']
        target = self.env['mail.thread']._restagrup_match_existing('incident', msg_dict)
        source = self.env[target[0]].browse(target[1]) if target else None
        log._notify(self, _('URGENTE: incidencia en un correo — %s') % (self.name or ''), self.summary, source)

    def action_mark_done(self):
        self.ai_log_id._close('confirmed')
        self.write({'state': 'done'})

    def action_create_lead(self):
        """Rescate: la IA se equivocó y era una petición de verdad. Crea el lead con el texto original y le
        pasa la extracción de datos, igual que un correo que hubiera entrado como petición nueva."""
        self.ensure_one()
        if self.lead_id:
            raise UserError(_('De este correo ya se creó el lead «%s».') % self.lead_id.name)
        original = self._original_email()
        lead = self.env['crm.lead'].create({
            'name': self.name, 'email_from': self.email_from, 'description': original.body or False,
        })
        lead._restagrup_extract_from_email({'body': original.body or ''})
        self.ai_log_id._close('corrected')  # la IA no lo vio como petición y lo era
        self.write({'lead_id': lead.id, 'state': 'done'})
        return {
            'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': lead.id,
            'view_mode': 'form', 'target': 'current',
        }
