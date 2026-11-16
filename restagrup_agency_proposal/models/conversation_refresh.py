# -*- coding: utf-8 -*-
"""Reunión 13/11 (P13): la pestaña Conversación del grupo se actualiza sola. Al guardarse un mensaje de la
conversación (correo o comentario, no notas internas) en el lead, su pedido, una tarjeta del buscador o la hoja del
restaurante, se avisa por el bus a los usuarios internos con el lead afectado; la ficha abierta se recarga."""
import logging

from odoo import api, models

from .lead_conversation import CONVERSATION_TYPES

_logger = logging.getLogger(__name__)

BUS_TYPE = 'restagrup_conversation_refresh'


class MailMessageConversationRefresh(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        messages._restagrup_notify_conversation()
        return messages

    def _restagrup_conversation_leads(self):
        """Leads cuya conversación incluye estos mensajes."""
        leads = self.env['crm.lead']
        for message in self.sudo():
            if message.message_type not in CONVERSATION_TYPES or not message.model or not message.res_id:
                continue
            if message.message_type == 'comment' and message.subtype_id.internal:
                continue
            if message.model not in ('crm.lead', 'sale.order', 'purchase.order', 'restagrup.restaurant.search.line'):
                continue
            record = self.env[message.model].sudo().browse(message.res_id).exists()
            if message.model == 'crm.lead':
                leads |= record
            elif message.model == 'sale.order':
                leads |= record.opportunity_id | self.env['restagrup.restaurant.search'].sudo().search(
                    [('sale_order_id', '=', record.id)]).lead_id
            elif message.model == 'purchase.order':
                order = record.restagrup_sale_order_id
                leads |= order.opportunity_id | self.env['restagrup.restaurant.search'].sudo().search(
                    [('sale_order_id', '=', order.id)]).lead_id if order else leads.browse()
            else:
                leads |= record.search_id.lead_id
        return leads

    def _restagrup_notify_conversation(self):
        leads = self._restagrup_conversation_leads()
        if not leads:
            return
        users = self.env['res.users'].sudo().search([('share', '=', False), ('active', '=', True)])
        for lead in leads:
            for user in users:
                try:
                    self.env['bus.bus'].sudo()._sendone(user.partner_id, BUS_TYPE, {'lead_id': lead.id})
                except Exception:  # noqa: BLE001 -- avisar nunca debe impedir guardar el mensaje
                    _logger.exception('No se pudo avisar del mensaje nuevo en el grupo %s', lead.id)
