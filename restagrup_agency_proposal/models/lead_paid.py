# -*- coding: utf-8 -*-
"""Casilla «Pagado» en el propio expediente (ronda de ajustes 11/11).

Como en su CRM: si el justificante llega por WhatsApp, se marca en la ficha del grupo sin ir a «Pagos pendientes».
Refleja y cambia el pago de los pedidos del grupo (no se guarda aparte)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CrmLeadPaid(models.Model):
    _inherit = 'crm.lead'

    restagrup_paid = fields.Boolean(
        string='Pagado', compute='_compute_restagrup_paid', inverse='_inverse_restagrup_paid',
        help='La agencia ha pagado. Marcarlo aquí marca como pagados los pedidos del grupo.')

    @api.depends('order_ids.restagrup_paid', 'order_ids.state')
    def _compute_restagrup_paid(self):
        for lead in self:
            orders = lead._restagrup_close_orders()
            lead.restagrup_paid = bool(orders) and all(orders.mapped('restagrup_paid'))

    def _inverse_restagrup_paid(self):
        for lead in self:
            orders = lead._restagrup_close_orders()
            if not orders and not lead.restagrup_paid:
                continue  # crear el grupo desde el formulario manda «Pagado = No»: no hay nada que cambiar
            if not orders:
                raise UserError(_('Este grupo aún no tiene pedido confirmado: no hay nada que marcar como pagado.'))
            if lead.restagrup_paid:
                orders.filtered(lambda order: not order.restagrup_paid).action_mark_paid()
            else:
                orders.filtered('restagrup_paid').action_unmark_paid()
