# -*- coding: utf-8 -*-
"""«Pasar a expediente» exige el presupuesto de venta (ronda de ajustes 09/11).

Rubén pasó un grupo a expediente sin presupuesto de venta: no había pedido, ni hoja para el restaurante, ni proforma.
Ahora, al pasar: si ya hay presupuesto se confirma; si no, se crea con lo elegido en cada servicio y se confirma.
Sin restaurante elegido no se puede (el mensaje dice qué falta). El contexto `restagrup_file_without_order` lo
salta (datos antiguos, demos y pruebas de las fases)."""
from odoo import _, models
from odoo.exceptions import UserError


class CrmLeadFile(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_do_pass_to_file(self):
        if self.env.context.get('restagrup_file_without_order'):
            return super()._restagrup_do_pass_to_file()
        for lead in self:
            pending = lead._restagrup_prepare_order_for_file()
            if pending:
                return pending
        return super()._restagrup_do_pass_to_file()

    def _restagrup_prepare_order_for_file(self):
        """Deja el pedido confirmado. Devuelve una acción si falta un paso (confirmar un precio, elegir menú)."""
        self.ensure_one()
        orders = self._restagrup_live_orders()
        if not orders:
            if not self.restagrup_restaurant_search_ids:
                raise UserError(_(
                    'Para pasar a expediente hace falta el restaurante: busca y elige uno para cada servicio.'))
            result = self.action_create_joint_quote()
            orders = self._restagrup_live_orders()
            if not orders:
                return result
        orders.filtered(lambda order: order.state in ('draft', 'sent')).action_confirm()
        return None
