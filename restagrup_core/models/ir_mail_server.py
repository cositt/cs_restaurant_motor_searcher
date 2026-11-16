# -*- coding: utf-8 -*-
"""Reunión 13/11 (P14): todo correo que sale por SMTP lo hace desde el buzón de salida con el nombre
«Restagrup · usuario», en vez de «usuario» <buzón> que deja Odoo cuando el remitente no es el del servidor."""
from odoo import models


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    def _build_email__(self, email_from, *args, **kwargs):  # noqa: PLW3201 (nombre de Odoo 19)
        email_from = self.env['restagrup.system.mail'].outgoing_from(email_from)
        return super()._build_email__(email_from, *args, **kwargs)
