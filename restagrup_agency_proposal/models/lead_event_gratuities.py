# -*- coding: utf-8 -*-
"""Reunión 13/11 (P3): las gratuidades se apuntan en el servicio y pasan a su línea de venta."""
from odoo import models


class RestagrupLeadEventGratuities(models.Model):
    _inherit = 'restagrup.lead.event'

    def write(self, vals):
        res = super().write(vals)
        if 'gratuities' in vals:
            for event in self:
                lines = self.env['sale.order.line'].search([
                    ('restagrup_search_line_id.search_id.event_id', '=', event.id),
                    ('order_id.state', '!=', 'cancel'), ('display_type', '=', False)])
                lines.filtered(lambda l: l.restagrup_gratuities != event.gratuities).write(
                    {'restagrup_gratuities': event.gratuities})
        return res
