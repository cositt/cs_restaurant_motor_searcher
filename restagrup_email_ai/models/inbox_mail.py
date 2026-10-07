# -*- coding: utf-8 -*-
from odoo import _, fields, models
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
    _inherit = ['mail.thread']
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
    lead_id = fields.Many2one('crm.lead', string='Lead creado', readonly=True, copy=False, ondelete='set null')

    def _original_email(self):
        self.ensure_one()
        emails = self.message_ids.filtered(lambda m: m.message_type == 'email')
        return emails[-1:]

    def action_mark_done(self):
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
        self.write({'lead_id': lead.id, 'state': 'done'})
        return {
            'type': 'ir.actions.act_window', 'res_model': 'crm.lead', 'res_id': lead.id,
            'view_mode': 'form', 'target': 'current',
        }
