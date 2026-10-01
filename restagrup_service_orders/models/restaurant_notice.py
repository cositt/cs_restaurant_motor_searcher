# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import html2plaintext

EXCERPT_CHARS = 300


class RestagrupRestaurantNotice(models.Model):
    _name = 'restagrup.restaurant.notice'
    _description = 'Aviso enviado a un restaurante de un grupo'
    _order = 'sent_date desc, id desc'

    lead_id = fields.Many2one('crm.lead', string='Grupo / Cliente', required=True, ondelete='cascade', index=True)
    restaurant_id = fields.Many2one('res.partner', string='Restaurante', required=True)
    event_label = fields.Char(string='Evento')
    subject = fields.Char(string='Asunto')
    body = fields.Html(string='Texto', sanitize=False)
    sent_date = fields.Datetime(string='Enviado', default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='Enviado por', default=lambda self: self.env.user)
    thread_model = fields.Char(string='Hilo (modelo)')
    thread_res_id = fields.Integer(string='Hilo (id)')
    mail_message_id = fields.Many2one('mail.message', string='Correo enviado', ondelete='set null')
    state = fields.Selection(
        selection=[('pending', 'Pendiente de respuesta'), ('replied', 'Respondido')],
        string='Estado', default='pending', required=True,
    )
    reply_date = fields.Datetime(string='Respondido')
    reply_excerpt = fields.Text(string='Respuesta')
    reply_summary = fields.Text(string='Resumen IA')

    @api.model
    def _register_reply(self, record, msg_dict, summary=False):
        """Una respuesta entrante en el hilo de un aviso lo marca como respondido. Se enlaza por el correo
        al que contesta (parent_id); si no consta, el aviso pendiente más reciente de ese hilo."""
        pending = self.sudo().search([
            ('thread_model', '=', record._name), ('thread_res_id', '=', record.id), ('state', '=', 'pending'),
        ], order='sent_date desc, id desc')
        if not pending:
            return
        parent_id = msg_dict.get('parent_id')
        notice = pending.filtered(lambda n: parent_id and n.mail_message_id.id == parent_id)[:1] or pending[:1]
        text = html2plaintext(msg_dict.get('body') or '').strip()
        notice.write({
            'state': 'replied',
            'reply_date': fields.Datetime.now(),
            'reply_excerpt': text[:EXCERPT_CHARS] + ('…' if len(text) > EXCERPT_CHARS else ''),
            'reply_summary': summary or False,
        })
