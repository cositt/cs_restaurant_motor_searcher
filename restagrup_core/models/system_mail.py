# -*- coding: utf-8 -*-
from odoo import api, models


class RestagrupSystemMail(models.AbstractModel):
    _name = 'restagrup.system.mail'
    _description = 'Remitente de los correos que genera el sistema'

    @api.model
    def email_from(self, fallback=False):
        """Cuenta dedicada desde la que salen los envíos del sistema (Ajustes > Restagrup); si no hay, el
        remitente que se pasa (el del usuario o responsable)."""
        sender = (self.env['ir.config_parameter'].sudo().get_param('restagrup.system_sender') or '').strip()
        return sender or fallback
