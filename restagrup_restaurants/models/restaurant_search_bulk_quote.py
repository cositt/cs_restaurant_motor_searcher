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
        Los que no tienen email se quedan como interesados y se avisa de cuáles son.
        Reunión 12/11 (4.1): antes se revisa en una ventana un texto común para todos; {restaurante} y {menu} se
        rellenan con los de cada uno."""
        self.ensure_one()
        interested = self._interested_lines()
        catalogue_note = self._catalogue_pending_note()
        if not interested:
            raise UserError(_('No hay ningún restaurante marcado como «Interesado» en esta búsqueda.')
                            + catalogue_note)
        for line in interested.filtered(lambda l: not (l.partner_id.email or l.email)):
            line._restagrup_find_web_email()  # ronda 11/11: los de Google, con el email de su web
        with_email = interested.filtered(lambda line: (line.partner_id.email or line.email or '').strip())
        skipped = interested - with_email
        if not with_email:
            raise UserError(_(
                'Ninguno de los interesados tiene email de contacto (%s). Añádelos como contacto'
                ' o edita su email antes de pedir presupuesto.') % ', '.join(skipped.mapped('name'))
                + catalogue_note)
        return with_email._restagrup_open_common_quote_request(skipped)

    def _catalogue_pending_note(self):
        """Los que tienen presupuesto de catálogo ya no están como interesados (ronda de ajustes 11/11: Conchita
        no entendía por qué Los Arcos, con email, no recibía la petición)."""
        pending = self.line_ids.filtered(
            lambda line: line.etiqueta == 'presupuesto_recibido' and line.quote_availability_pending)
        if not pending:
            return ''
        return '\n\n' + _(
            'Ya tienen presupuesto con el precio del catálogo (no se les vuelve a pedir): %s. Falta que confirmen'
            ' la disponibilidad: pregúntaselo y pulsa «Disponibilidad OK» en su tarjeta.'
        ) % ', '.join(pending.mapped('name'))

    def _bulk_quote_summary(self, sent, skipped):
        message = _('Presupuesto pedido a %(count)s restaurante(s): %(names)s.') % {
            'count': len(sent), 'names': ', '.join(sent.mapped('name'))}
        if skipped:
            message += ' ' + _('Sin email, siguen como interesados: %s.') % ', '.join(skipped.mapped('name'))
        return message


class RestaurantSearchLineBulkQuote(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def _restagrup_open_common_quote_request(self, skipped):
        """Ventana «Revisar y enviar» con un texto común para estas líneas (todas de la misma búsqueda)."""
        first = self[:1]
        values = dict(first._mail_values(self.env.user.name), restaurante='{restaurante}', menu='{menu}')
        subject, body_text = first._quote_request_content(values)
        summary = '\n'.join('%s — %s%s' % (
            line.name, line._get_quote_email_to(), ' ⚠ %s' % line.warnings_text if line.warnings_text else '')
            for line in self)
        if skipped:
            summary += '\n\n' + _('Sin email, siguen como interesados: %s.') % ', '.join(skipped.mapped('name'))
        summary += '\n\n' + _('{restaurante} y {menu} se cambian por los de cada restaurante.')
        return self.env['restagrup.send.wizard']._open_for(
            self, subject, body_text, title=_('Pedir presupuesto a %s interesados') % len(self), summary=summary)

    def _restagrup_after_multi_send(self):
        search = self.search_id[:1]
        skipped = search._interested_lines() - self  # los enviados ya están como «Solicitado»
        message = search._bulk_quote_summary(self, skipped)
        search.message_post_if_exists(Markup('<p>%s</p>') % message)
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
