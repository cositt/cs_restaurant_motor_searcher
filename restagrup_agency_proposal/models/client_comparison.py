# -*- coding: utf-8 -*-
import secrets

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

REPORT = 'restagrup_agency_proposal.report_client_comparison'


class RestaurantSearchPortal(models.Model):
    _inherit = 'restagrup.restaurant.search'

    comparison_token = fields.Char(
        string='Token de la comparativa', copy=False, index=True, groups='base.group_user',
        help='Se genera solo cuando se envía la comparativa con enlace de portal.',
    )

    def _comparison_portal_url(self):
        """Enlace público de la comparativa; crea el token la primera vez y lo reutiliza después."""
        self.ensure_one()
        if not self.comparison_token:
            self.sudo().comparison_token = secrets.token_urlsafe(24)
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        return '%s/comparativa/%s/%s' % (base, self.id, self.comparison_token)


class ClientComparisonWizard(models.TransientModel):
    _name = 'restagrup.client.comparison.wizard'
    _description = 'Enviar la comparativa de restaurantes al cliente'

    search_id = fields.Many2one('restagrup.restaurant.search', string='Búsqueda', required=True, readonly=True)
    email_to = fields.Char(string='Para', default=lambda self: self._default_email_to())
    subject = fields.Char(string='Asunto')
    body = fields.Text(string='Mensaje')
    include_portal_link = fields.Boolean(
        string='Incluir enlace de portal', default=False,
        help='Además del PDF, el correo lleva un enlace donde el cliente puede ver la comparativa y elegir.'
             ' Sin marcar, solo se envía el PDF.',
    )

    @api.model
    def _default_email_to(self):
        search = self.env['restagrup.restaurant.search'].browse(self.env.context.get('default_search_id'))
        return search.lead_id._restagrup_sender_email() if search.lead_id else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            search = self.env['restagrup.restaurant.search'].browse(vals.get('search_id'))
            vals.setdefault('subject', _('Comparativa de restaurantes — %s', search.city or search.display_name))
            vals.setdefault('body', _(
                'Hola,\n\nTe enviamos la comparativa de los restaurantes que nos han presupuestado,'
                ' con el menú y el precio por persona de cada uno, para que puedas elegir el que mejor te encaje.'
                '\n\nUn saludo,'
            ))
            if 'email_to' not in vals and search.lead_id:
                vals['email_to'] = search.lead_id._restagrup_sender_email()
        return super().create(vals_list)

    def action_send(self):
        self.ensure_one()
        search = self.search_id
        email_to = (self.email_to or '').strip()
        if not email_to:
            raise UserError(_('Indica el email del cliente al que se envía la comparativa.'))
        if not search.restagrup_comparison_rows():
            raise UserError(_('Aún no hay presupuestos confirmados que comparar.'))
        lead = search.lead_id
        pdf, _kind = self.env['ir.actions.report']._render_qweb_pdf(REPORT, search.ids)
        attachment = self.env['ir.attachment'].create({
            'name': _('Comparativa de restaurantes.pdf'), 'raw': pdf, 'mimetype': 'application/pdf',
            'res_model': lead._name, 'res_id': lead.id,
        })
        lines = [Markup.escape(line) for line in (self.body or '').splitlines()]
        body = Markup('<br/>').join(lines)
        if self.include_portal_link:
            url = search._comparison_portal_url()
            body += Markup('<br/><br/>%s<br/><a href="%s">%s</a>') % (
                _('También puedes verla y elegir online aquí:'), url, url)
        lead.message_post(
            body=body, subject=self.subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(lead.user_id.email or self.env.user.email),
            outgoing_email_to=email_to, attachment_ids=[attachment.id],
        )
        lead._restagrup_advance_to('presupuesto')  # enviada la propuesta, el grupo pasa a Presupuesto
        return {'type': 'ir.actions.act_window_close'}
