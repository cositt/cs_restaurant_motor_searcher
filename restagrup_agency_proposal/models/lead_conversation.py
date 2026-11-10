# -*- coding: utf-8 -*-
"""Toda la conversación del grupo en una pestaña (ronda de ajustes 09/11).

Los correos con la agencia (en el grupo y en su pedido) y con los restaurantes (peticiones de presupuesto y hojas
de servicio) se ven en un solo hilo, del más reciente al más antiguo. Cada interlocutor tiene su color: agencia
(azul), restaurante (naranja), RestaGrup (verde). El filtro deja ver solo la parte de la agencia o la de los
restaurantes. Las notas internas y los avisos automáticos no salen: esto es la conversación."""
from markupsafe import Markup, escape

from odoo import _, api, fields, models

CONVERSATION_TYPES = ('email', 'comment', 'email_outgoing')
FILTERS = [('all', 'Todo'), ('agency', 'Agencia'), ('restaurant', 'Restaurantes')]
WHO_LABELS = {'agency': 'Agencia', 'restaurant': 'Restaurante', 'restagrup': 'RestaGrup'}
STYLE = Markup(
    '<style>'
    '.o_rg_conv{display:flex;flex-direction:column;gap:8px}'
    '.o_rg_msg{border-radius:8px;padding:8px 12px;max-width:85%;border-left:4px solid}'
    '.o_rg_msg_agency{background:#e8f1fb;border-color:#2f6fb3;align-self:flex-start}'
    '.o_rg_msg_restaurant{background:#fdf0e3;border-color:#c46a12;align-self:flex-start}'
    '.o_rg_msg_restagrup{background:#e7f6ec;border-color:#2e8b57;align-self:flex-end}'
    '.o_rg_msg_head{font-size:.85em;color:#555;margin-bottom:4px}'
    '</style>')


class CrmLeadConversation(models.Model):
    _inherit = 'crm.lead'

    restagrup_conversation_filter = fields.Selection(
        FILTERS, string='Ver', default='all', help='Filtra la conversación del grupo por interlocutor.')
    restagrup_conversation_html = fields.Html(
        string='Conversación', compute='_compute_restagrup_conversation', sanitize=False)

    def _restagrup_conversation_threads(self):
        """[(registro, lado, nombre del restaurante)] con todo lo que se habla en el grupo."""
        self.ensure_one()
        lead = self.sudo()
        threads = [(lead, 'agency', '')]
        threads += [(order, 'agency', '') for order in lead._restagrup_live_orders()]
        for search in lead.restagrup_restaurant_search_ids:
            threads += [(line, 'restaurant', line.name or '') for line in search.line_ids]
        for sheet in lead._restagrup_live_orders().restaurant_po_ids:
            threads.append((sheet, 'restaurant', sheet.partner_id.name or ''))
        return threads

    def _restagrup_conversation_entries(self):
        self.ensure_one()
        entries, seen = [], set()
        root = self.env.ref('base.partner_root', raise_if_not_found=False)
        for record, side, restaurant in self._restagrup_conversation_threads():
            for message in record.message_ids:
                if message.id in seen or message.message_type not in CONVERSATION_TYPES:
                    continue
                if message.message_type == 'comment' and message.subtype_id.internal:
                    continue  # nota interna: no es conversación
                seen.add(message.id)
                internal = message.author_id == root or any(
                    not user.share for user in message.author_id.with_context(active_test=False).user_ids)
                entries.append({
                    'message': message, 'side': side, 'restaurant': restaurant,
                    'who': 'restagrup' if internal else side,
                })
        return sorted(entries, key=lambda entry: (entry['message'].date, entry['message'].id), reverse=True)

    @api.depends('restagrup_conversation_filter', 'message_ids')
    def _compute_restagrup_conversation(self):
        for lead in self:
            if not lead.id:
                lead.restagrup_conversation_html = False
                continue
            wanted = lead.restagrup_conversation_filter or 'all'
            entries = [entry for entry in lead._restagrup_conversation_entries()
                       if wanted == 'all' or entry['side'] == wanted]
            if not entries:
                lead.restagrup_conversation_html = Markup('<p class="text-muted">%s</p>') % _(
                    'Todavía no hay conversación.')
                continue
            lead.restagrup_conversation_html = STYLE + Markup('<div class="o_rg_conv">%s</div>') % Markup('').join(
                lead._restagrup_conversation_bubble(entry) for entry in entries)

    def _restagrup_conversation_bubble(self, entry):
        message = entry['message']
        author = message.author_id.name or message.email_from or ''
        where = entry['restaurant'] if entry['side'] == 'restaurant' and entry['restaurant'] != author else ''
        head = ' · '.join(part for part in (
            fields.Datetime.context_timestamp(self, message.date).strftime('%d/%m/%Y %H:%M') if message.date else '',
            WHO_LABELS[entry['who']], author, where and (_('con %s') % where)) if part)
        subject = Markup('<div><b>%s</b></div>') % message.subject if message.subject else Markup('')
        return Markup('<div class="o_rg_msg o_rg_msg_%s"><div class="o_rg_msg_head">%s</div>%s%s</div>') % (
            entry['who'], escape(head), subject, Markup(message.body or ''))
