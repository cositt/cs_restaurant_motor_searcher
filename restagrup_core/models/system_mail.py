# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.tools import email_normalize, formataddr

DEFAULT_SENDER_NAME = 'Restagrup'
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
    def sender_address(self):
        """Reunión 13/11 (P14): buzón desde el que salen los correos. El de Ajustes > Restagrup; si no, el remitente
        por defecto de Odoo (dominio de alias, «mail.default.from» o el «from_filter» del servidor de salida).
        Vacío si no hay ninguno: entonces no se cambia nada."""
        params = self.env['ir.config_parameter'].sudo()
        candidates = [
            params.get_param('restagrup.system_sender'),
            self.env['ir.mail_server'].sudo()._get_default_from_address(),
            params.get_param('mail.default.from'),
        ]
        server = self.env['ir.mail_server'].sudo().search([], order='sequence, id', limit=1)
        candidates += [part for part in (server.from_filter or '').split(',')] + [server.smtp_user]
        for candidate in candidates:
            address = email_normalize((candidate or '').strip())
            if address:
                return address
        return False

    @api.model
    def sender_name(self, user):
        """«Restagrup · Ruben»: la marca (Ajustes) y quién escribe."""
        brand = (self.env['ir.config_parameter'].sudo().get_param('restagrup.sender_name') or '').strip()
        brand = brand or DEFAULT_SENDER_NAME
        return '%s · %s' % (brand, user.name) if user and user.name else brand

    @api.model
    def outgoing_from(self, email_from):
        """El remitente con el que debe salir un correo: si es de un usuario interno, «Marca · usuario» <buzón de
        salida>; si ya es el buzón de salida, «Marca» <buzón>. Lo de agencias y restaurantes no se toca."""
        outbox = self.sender_address()
        address = email_normalize(email_from) if email_from else False
        if not outbox or not address:
            return email_from
        user = self.env['res.users'].sudo().with_context(active_test=False).search(
            [('share', '=', False), '|', ('email', '=ilike', address), ('login', '=ilike', address)], limit=1)
        if address != outbox and not user:
            return email_from
        return formataddr((self.sender_name(user), outbox))

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
