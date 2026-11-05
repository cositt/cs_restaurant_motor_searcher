# -*- coding: utf-8 -*-
"""Propuesta conjunta desde la petición (PPT de Conchita 2026-11-04, urgente 4): todos los servicios del grupo
en una sola propuesta (correo + PDF + enlace donde la agencia elige un restaurante por servicio) y un único
presupuesto de venta con todos los servicios elegidos. Al cliente se le escribe solo desde la petición."""
import secrets

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang

REPORT = 'restagrup_agency_proposal.report_client_comparison'


class CrmLeadProposal(models.Model):
    _inherit = 'crm.lead'

    restagrup_proposal_token = fields.Char(
        string='Token de la propuesta', copy=False, index=True, groups='base.group_user')
    restagrup_proposal_line_ids = fields.Many2many(
        'restagrup.restaurant.search.line', string='Presupuestos recibidos',
        compute='_compute_restagrup_proposal', help='Los restaurantes con presupuesto de cada servicio.')
    restagrup_candidate_menu_ids = fields.Many2many(
        'restagrup.restaurant.menu', string='Menús de los restaurantes candidatos',
        compute='_compute_restagrup_proposal')
    restagrup_proposal_ready = fields.Boolean(compute='_compute_restagrup_proposal')
    restagrup_quote_ready = fields.Boolean(compute='_compute_restagrup_proposal')

    @api.depends('restagrup_restaurant_search_ids.line_ids.etiqueta',
                 'restagrup_restaurant_search_ids.line_ids.menu_id',
                 'restagrup_restaurant_search_ids.chosen_line_id')
    def _compute_restagrup_proposal(self):
        Menu = self.env['restagrup.restaurant.menu']
        for lead in self:
            lines = lead.restagrup_restaurant_search_ids.line_ids
            received = lines.filtered(lambda l: l.etiqueta == 'presupuesto_recibido' and l.quote_amount)
            candidates = lines.filtered(lambda l: l.partner_id and l.etiqueta not in ('descartado', 'cancelado'))
            lead.restagrup_proposal_line_ids = received
            lead.restagrup_candidate_menu_ids = Menu.search([('partner_id', 'in', candidates.partner_id.ids)]) \
                if candidates else Menu
            lead.restagrup_proposal_ready = bool(received)
            lead.restagrup_quote_ready = any(
                search.chosen_line_id and not search.sale_order_id for search in lead.restagrup_restaurant_search_ids)

    # --- servicios de la propuesta ---

    def _restagrup_proposal_searches(self):
        """Una búsqueda por servicio, en el orden de los servicios (fecha y hora)."""
        self.ensure_one()
        return self.restagrup_restaurant_search_ids.sorted(lambda s: (
            s.event_id.event_date or fields.Date.today().replace(year=9999), s.event_id.event_time or 0.0, s.id))

    @api.model
    def _restagrup_service_label(self, search):
        event = search.event_id
        parts = [search.city or event.city or '']
        if event.event_date:
            parts.append(event.event_date.strftime('%d/%m/%Y'))
        if event.event_type_id:
            parts.append(event.event_type_id.name)
        pax = event.pax or search.min_capacity
        if pax:
            parts.append(_('%s personas') % pax)
        return ' · '.join(part for part in parts if part)

    def _restagrup_proposal_sections(self):
        """[{'search', 'label', 'rows'}] para el portal y la revisión antes de enviar."""
        self.ensure_one()
        return [{'search': search, 'label': self._restagrup_service_label(search),
                 'rows': search.restagrup_comparison_rows()} for search in self._restagrup_proposal_searches()]

    def _restagrup_proposal_portal_url(self):
        self.ensure_one()
        if not self.restagrup_proposal_token:
            self.sudo().restagrup_proposal_token = secrets.token_urlsafe(24)
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        return '%s/propuesta/%s/%s' % (base, self.id, self.restagrup_proposal_token)

    # --- acciones de la petición ---

    def action_open_proposal_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Enviar propuesta a la agencia'),
            'res_model': 'restagrup.lead.proposal.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_create_joint_quote(self):
        """Un presupuesto de venta con todos los servicios: cada servicio con su restaurante elegido."""
        self.ensure_one()
        searches = self._restagrup_proposal_searches()
        if not searches:
            raise UserError(_('Este grupo aún no tiene búsquedas de restaurante.'))
        missing = searches.filtered(lambda s: not s.chosen_line_id and not s.sale_order_id)
        if missing:
            raise UserError(_('Elige antes un restaurante para cada servicio. Falta en: %s.') % '; '.join(
                self._restagrup_service_label(search) for search in missing))
        for search in searches.filtered(lambda s: not s.sale_order_id):
            search.action_create_sale_order()
        order = searches.sale_order_id.filtered(lambda o: o.state != 'cancel')[:1]
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': order.id,
            'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current',
        }


class LeadProposalWizard(models.TransientModel):
    _name = 'restagrup.lead.proposal.wizard'
    _inherit = ['restagrup.firewall.mixin']
    _description = 'Enviar la propuesta de todos los servicios a la agencia'

    lead_id = fields.Many2one('crm.lead', string='Grupo', required=True, readonly=True)
    email_to = fields.Char(string='Para')
    subject = fields.Char(string='Asunto')
    body = fields.Text(string='Mensaje')
    include_portal_link = fields.Boolean(
        string='Incluir enlace para elegir', default=True,
        help='Además del PDF, un enlace donde la agencia ve la propuesta y elige un restaurante por servicio.')
    show_restaurants = fields.Boolean(
        string='Mostrar los restaurantes', default=True,
        help='Si no se marca, la agencia ve «Opción 1», «Opción 2»… con su menú y su precio, sin el nombre.')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        lead = self.env['crm.lead'].browse(values.get('lead_id') or self.env.context.get('default_lead_id'))
        if lead:
            values.setdefault('email_to', lead._restagrup_agency_email())
            values.setdefault('subject', self._default_subject_for(lead))
        values.setdefault('body', self._default_body_text())
        return values

    @api.model
    def _default_subject_for(self, lead):
        if not lead:
            return False
        parts = [_('Propuesta de restaurantes'), lead.name, lead._restagrup_locator()]
        return ' — '.join(part for part in parts if part)

    @api.model
    def _default_body_text(self):
        return _('Hola,\n\nTe enviamos la propuesta de restaurantes para vuestro grupo, con el menú y el precio por'
                 ' persona de cada opción, servicio a servicio, para que elijas la que mejor os encaje.\n\nUn saludo,')

    def _restagrup_firewall_log_target(self):
        return self.lead_id

    def _validate(self):
        self.ensure_one()
        if not (self.email_to or '').strip():
            raise UserError(_('Indica el email de la agencia a la que se envía la propuesta.'))
        sections = self.lead_id._restagrup_proposal_sections()
        if not sections:
            raise UserError(_('Este grupo aún no tiene búsquedas de restaurante.'))
        empty = [section['label'] for section in sections if not section['rows']]
        if empty:
            raise UserError(_('Aún no hay presupuestos confirmados que proponer en: %s.') % '; '.join(empty))

    def _fw_review_proposal(self):
        self.ensure_one()
        blocks = []
        for section in self.lead_id._restagrup_proposal_sections():
            options = '\n'.join('  • %s — %s € por persona%s' % (
                row['line'].name, formatLang(self.env, row['price_per_person'], digits=2),
                (' · %s' % row['menu'].name) if row['menu'] else '') for row in section['rows'])
            blocks.append('%s\n%s' % (section['label'], options))
        return _(
            'Se enviará a %(email)s la propuesta con estos servicios y opciones:\n\n%(blocks)s\n\n'
            'Nombres de restaurante visibles: %(visible)s · Enlace para elegir: %(portal)s\n'
            'Sin totales: el total llega con el presupuesto.') % {
            'email': (self.email_to or '').strip(), 'blocks': '\n\n'.join(blocks),
            'visible': _('sí') if self.show_restaurants else _('no, solo «Opción N»'),
            'portal': _('sí') if self.include_portal_link else _('no')}

    def action_send(self):
        self.ensure_one()
        self._validate()
        return self._restagrup_gated('send_proposal', '_restagrup_do_send')

    def _restagrup_do_send(self):
        self.ensure_one()
        self._validate()
        lead = self.lead_id
        searches = lead._restagrup_proposal_searches()
        searches.write({'restaurant_visible': self.show_restaurants})
        pdf, _kind = self.env['ir.actions.report']._render_qweb_pdf(REPORT, searches.ids)
        attachment = self.env['ir.attachment'].create({
            'name': _('Propuesta de restaurantes.pdf'), 'raw': pdf, 'mimetype': 'application/pdf',
            'res_model': lead._name, 'res_id': lead.id,
        })
        body = Markup('<br/>').join(Markup.escape(line) for line in (self.body or '').splitlines())
        if self.include_portal_link:
            url = lead._restagrup_proposal_portal_url()
            body += Markup('<br/><br/>%s<br/><a href="%s">%s</a>') % (
                _('También puedes verla y elegir online aquí:'), url, url)
        lead.message_post(
            body=body, subject=self.subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(lead.user_id.email or self.env.user.email),
            email_add_signature=False, outgoing_email_to=(self.email_to or '').strip(),
            attachment_ids=[attachment.id],
        )
        lead._restagrup_advance_to('presupuesto')
        return {'type': 'ir.actions.act_window_close'}
