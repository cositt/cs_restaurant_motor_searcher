# -*- coding: utf-8 -*-
"""Reunión 13/11 (P14): agencias y restaurantes reciben los correos del buzón de salida con el nombre
«Restagrup · <usuario>» (antes llegaban como «Ruben»).

Se hace al final de la preparación del envío, cuando Odoo ya ha decidido cabecera y sobre para la sesión SMTP:
- si no hay servidor para el correo del usuario, Odoo lo deja tal cual y Gmail cambiaba solo la dirección por la
  de la cuenta, conservando «Ruben»;
- si lo encapsula, Odoo pone el buzón con el nombre del usuario (o sin nombre).
En ambos casos el correo de un usuario interno (o del propio buzón) sale con From «Restagrup · usuario» <buzón> y
el sobre del buzón. Los remitentes externos no se tocan."""
from odoo import models
from odoo.tools import email_normalize


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    def _prepare_email_message__(self, message, smtp_session):  # noqa: PLW3201
        original_from = message['From']
        smtp_from, smtp_to_list, message = super()._prepare_email_message__(message, smtp_session)
        wanted = self.env['restagrup.system.mail'].outgoing_from(original_from)
        if wanted and wanted != original_from:
            message.replace_header('From', wanted)
            smtp_from = email_normalize(wanted) or smtp_from
        return smtp_from, smtp_to_list, message
