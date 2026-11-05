# -*- coding: utf-8 -*-
"""Aviso de «siguiente paso» en el presupuesto: qué toca hacer ahora (PPT de Conchita 2026-11-04, diapositiva 8:
no sabía que faltaba pulsar «Enviar»)."""
from odoo import _, api, fields, models


class SaleOrderNextStep(models.Model):
    _inherit = 'sale.order'

    restagrup_next_step = fields.Char(string='Siguiente paso', compute='_compute_restagrup_next_step')

    @api.depends('state', 'restaurant_po_ids.state')
    def _compute_restagrup_next_step(self):
        for order in self:
            order.restagrup_next_step = order._restagrup_next_step_text()

    def _restagrup_next_step_text(self):
        self.ensure_one()
        if self.state == 'draft':
            return _('Siguiente paso: revisa el PDF («Imprimir») y pulsa «Enviar presupuesto a la agencia».')
        if self.state == 'sent':
            return _('Enviado. Siguiente paso: que la agencia lo firme desde el enlace del correo.')
        if self.state == 'sale':
            pending = self.restaurant_po_ids.filtered(lambda po: po.state in ('draft', 'to approve'))
            if pending:
                return _('Firmado. Siguiente paso: «Enviar hojas de servicio» a los restaurantes.')
        return False
