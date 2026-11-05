# -*- coding: utf-8 -*-
"""El presupuesto del grupo lleva el número de la petición (PET202611-17719, -2 si hay otro) y vale hasta
el día del primer servicio: así lo trabaja Restagrup (ticket de Conchita 2026-11-04)."""
from odoo import _, api, models


class SaleOrderNumbering(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('opportunity_id') and vals.get('name', _('New')) == _('New'):
                name = self._restagrup_petition_order_name(vals['opportunity_id'])
                if name:
                    vals['name'] = name
        return super().create(vals_list)

    @api.model
    def _restagrup_petition_order_name(self, lead_id):
        """Número de la petición tal como lo conoce el equipo (siempre con PET, aunque el grupo ya esté en
        presupuesto o expediente); los presupuestos siguientes del mismo grupo, con -2, -3..."""
        base = self.env['crm.lead'].browse(lead_id).exists()._restagrup_locator()
        if not base:
            return False
        candidate, suffix = base, 1
        while self.sudo().with_context(active_test=False).search_count([('name', '=', candidate)], limit=1):
            suffix += 1
            candidate = '%s-%s' % (base, suffix)
        return candidate

    @api.depends('restagrup_service_date')
    def _compute_validity_date(self):
        """Vale hasta el día del servicio, nunca después; sin servicio, la validez estándar."""
        super()._compute_validity_date()
        for order in self:
            if order.restagrup_service_date:
                order.validity_date = order.restagrup_service_date
