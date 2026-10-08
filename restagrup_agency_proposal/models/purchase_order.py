# -*- coding: utf-8 -*-
from odoo import models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def restagrup_document_services(self):
        """Servicios de la hoja de servicio con lo que cobra el restaurante (nunca el precio al cliente)."""
        self.ensure_one()
        sale_lines = self.order_line.mapped('restagrup_sale_line_id').sorted(
            lambda l: (l.service_date or l.create_date, l.service_hour or 0.0, l.id))
        return [dict(line._restagrup_service_info(), index=index) for index, line in enumerate(sale_lines, start=1)]

    def action_confirmation_restaurant(self):
        """Confirmación al restaurante: antes de generarla, el cortafuegos comprueba que todo cuadra."""
        return self._restagrup_gated('confirm_restaurant', '_restagrup_do_confirmation_restaurant')

    def _restagrup_do_confirmation_restaurant(self):
        return self.env.ref('restagrup_agency_proposal.action_report_restaurant_confirmation').report_action(self)
