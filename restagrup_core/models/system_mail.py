# -*- coding: utf-8 -*-
from odoo import api, models

# Buzón de entrada cuyas respuestas sin hilo conocido crean líneas del buscador: el que lee las de restaurantes.
REPLIES_MODEL = 'restagrup.restaurant.search.line'


class RestagrupSystemMail(models.AbstractModel):
    _name = 'restagrup.system.mail'
    _description = 'Remitente de los correos que genera el sistema'

    @api.model
    def email_from(self, fallback=False):
        """Cuenta dedicada desde la que salen los envíos del sistema (Ajustes > Restagrup); si no hay, el
        remitente que se pasa (el del usuario o responsable)."""
        sender = (self.env['ir.config_parameter'].sudo().get_param('restagrup.system_sender') or '').strip()
        return sender or fallback

    @api.model
    def reply_to(self):
        """Reunión 12/11 (4.3): buzón al que deben contestar restaurantes y agencias para que la respuesta entre en
        Odoo. El de Ajustes > Restagrup; si está vacío, el buzón de entrada que lee las respuestas de restaurantes."""
        mailbox = (self.env['ir.config_parameter'].sudo().get_param('restagrup.reply_to') or '').strip()
        if mailbox:
            return mailbox
        server = self.env['fetchmail.server'].sudo().search(
            [('object_id.model', '=', REPLIES_MODEL), ('user', 'like', '@')], order='id', limit=1)
        return (server.user or '').strip()


class Base(models.AbstractModel):
    _inherit = 'base'

    def _notify_get_reply_to_batch(self, defaults=None, author_ids=None):
        """Sin alias ni catchall, Odoo pone de «responder a» el email del remitente (el agente) y la respuesta no
        vuelve a Odoo. En ese caso se usa el buzón que lee Odoo; un dominio de alias de verdad sigue mandando."""
        result = super()._notify_get_reply_to_batch(defaults=defaults, author_ids=author_ids)
        mailbox = self.env['restagrup.system.mail'].reply_to()
        if not mailbox:
            return result
        defaults = defaults or {}
        author_ids = author_ids or {}
        return {
            res_id: self._notify_get_reply_to_formatted_email(mailbox, author_id=author_ids.get(res_id))
            if reply_to == defaults.get(res_id) else reply_to
            for res_id, reply_to in result.items()
        }
