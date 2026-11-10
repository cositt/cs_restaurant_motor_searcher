# -*- coding: utf-8 -*-
"""Cancelar o borrar una petición cancela también su pedido (ronda de ajustes 09/11).

Antes el pedido confirmado se quedaba vivo y sin grupo, y seguía saliendo en «Pagos pendientes». Si la agencia
ya ha pagado no se cancela en silencio: hay que resolver antes el pago (devolución o cambio)."""
from odoo import _, models
from odoo.exceptions import UserError


class CrmLeadCancel(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_live_orders(self):
        """Pedidos del grupo (por la oportunidad o por sus búsquedas) que no están cancelados."""
        searches = self.sudo().restagrup_restaurant_search_ids
        orders = self.sudo().order_ids | searches.sale_order_id
        return orders.filtered(lambda order: order.state != 'cancel')

    def _restagrup_cancel_orders(self):
        orders = self._restagrup_live_orders()
        if not orders:
            return
        paid = orders.filtered('restagrup_paid')
        if paid:
            raise UserError(_(
                'La agencia ya ha pagado %s: resuelve antes el pago (devolución o cambio) y luego cancela el grupo.'
            ) % ', '.join(paid.mapped('name')))
        sheets = self.env['purchase.order'].sudo().search([
            ('restagrup_sale_order_id', 'in', orders.ids), ('state', '!=', 'cancel')])
        sheets.button_cancel()
        orders._action_cancel()
        for lead in self:
            names = ', '.join(orders.filtered(lambda o, lead=lead: o.opportunity_id == lead).mapped('name'))
            if names:
                lead.message_post(body=_('Pedido cancelado con el grupo: %s.') % names)

    def action_set_lost(self, **additional_values):
        self._restagrup_cancel_orders()
        return super().action_set_lost(**additional_values)

    def unlink(self):
        self._restagrup_cancel_orders()
        return super().unlink()
