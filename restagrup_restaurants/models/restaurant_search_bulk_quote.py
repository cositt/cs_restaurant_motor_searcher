# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RestaurantSearch(models.Model):
    """Pedir presupuesto de una vez a todos los resultados marcados como «Interesado»."""
    _inherit = 'restagrup.restaurant.search'

    interested_count = fields.Integer(string='Interesados', compute='_compute_interested_count')

    @api.depends('line_ids.etiqueta')
    def _compute_interested_count(self):
        for search in self:
            search.interested_count = len(search._interested_lines())

    def _interested_lines(self):
        return self.line_ids.filtered(lambda line: line.etiqueta == 'interesado')

    def action_request_quote_interested(self):
        """Mismo correo que «Pedir presupuesto» en cada tarjeta, a todos los interesados con email.
        Los que no tienen email se quedan como interesados y se avisa de cuáles son."""
        self.ensure_one()
        interested = self._interested_lines()
        if not interested:
            raise UserError(_('No hay ningún restaurante marcado como «Interesado» en esta búsqueda.'))
        with_email = interested.filtered(lambda line: (line.partner_id.email or line.email or '').strip())
        skipped = interested - with_email
        if not with_email:
            raise UserError(_(
                'Ninguno de los interesados tiene email de contacto (%s). Añádelos como contacto'
                ' o edita su email antes de pedir presupuesto.') % ', '.join(skipped.mapped('name')))
        for line in with_email:
            line.action_request_quote()
        message = self._bulk_quote_summary(with_email, skipped)
        self.message_post_if_exists(Markup('<p>%s</p>') % message)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Presupuestos pedidos'),
                'message': message,
                'type': 'warning' if skipped else 'success',
                'sticky': bool(skipped),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _bulk_quote_summary(self, sent, skipped):
        message = _('Presupuesto pedido a %(count)s restaurante(s): %(names)s.') % {
            'count': len(sent), 'names': ', '.join(sent.mapped('name'))}
        if skipped:
            message += ' ' + _('Sin email, siguen como interesados: %s.') % ', '.join(skipped.mapped('name'))
        return message
