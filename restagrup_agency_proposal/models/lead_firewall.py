# -*- coding: utf-8 -*-
from odoo import _, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def _fw_paid(self):
        """Antes de cerrar el expediente, el cobro tiene que estar marcado como recibido."""
        orders = self._restagrup_firewall_orders().filtered(lambda o: o.state in ('sale', 'done'))
        if not orders:
            return _('No hay ningún presupuesto de venta confirmado en este grupo.')
        unpaid = orders.filtered(lambda o: not o.restagrup_paid)
        return _('El pago no está marcado como recibido en: %s.') % ', '.join(unpaid.mapped('name')) if unpaid else False
