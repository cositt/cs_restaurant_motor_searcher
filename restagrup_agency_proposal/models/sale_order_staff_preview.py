# -*- coding: utf-8 -*-
"""«Aceptar y firmar», «Rechazar» y pagar son de la agencia. Un empleado que abre el presupuesto en el portal
(«Vista previa») lo ve como lo verá la agencia, pero sin esos botones y sin poder usarlos (PPT de Conchita
2026-11-04, diapositiva 8). La demo lo permite con el parámetro restagrup.portal_staff_can_sign."""
from odoo import models
from odoo.tools import str2bool

STAFF_CAN_SIGN_PARAM = 'restagrup.portal_staff_can_sign'
PREVIEW_CONTEXT_KEY = 'restagrup_staff_preview'


class SaleOrderStaffPreview(models.Model):
    _inherit = 'sale.order'

    def _restagrup_customer_actions_allowed(self, user):
        """La agencia (usuario de portal o el enlace público) sí; un empleado, solo si la demo lo permite."""
        if user.share:
            return True
        return str2bool(self.env['ir.config_parameter'].sudo().get_param(STAFF_CAN_SIGN_PARAM) or 'False')

    def _restagrup_portal_order(self, user):
        """El presupuesto tal como se pinta en el portal para ese usuario."""
        if self._restagrup_customer_actions_allowed(user):
            return self
        return self.with_context(**{PREVIEW_CONTEXT_KEY: True})

    def _has_to_be_signed(self):
        if self.env.context.get(PREVIEW_CONTEXT_KEY):
            return False
        return super()._has_to_be_signed()

    def _has_to_be_paid(self):
        if self.env.context.get(PREVIEW_CONTEXT_KEY):
            return False
        return super()._has_to_be_paid()
