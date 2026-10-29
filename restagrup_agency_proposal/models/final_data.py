# -*- coding: utf-8 -*-
from odoo import _, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_final_missing(self):
        """Antes del servicio, además de los datos del evento: el justificante si la agencia aún no ha pagado."""
        missing = super()._restagrup_final_missing()
        orders = self.order_ids.filtered(lambda o: o.state != 'cancel')
        if orders and not any(orders.mapped('restagrup_paid')):
            missing.append(_('Justificante de pago'))
        return missing
