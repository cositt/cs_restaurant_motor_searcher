# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext


class RestagrupPendingMail(models.Model):
    """A2: correos de seguimiento (recordatorio a la agencia, aviso «grupo no sale») por la cola de aprobación."""
    _inherit = 'restagrup.pending.mail'

    kind = fields.Selection(selection_add=[
        ('agency_reminder', 'Recordatorio a la agencia'),
        ('group_cancelled', 'Aviso de grupo cancelado'),
    ], ondelete={'agency_reminder': 'cascade', 'group_cancelled': 'cascade'})
    sale_order_id = fields.Many2one(
        'sale.order', string='Presupuesto', ondelete='cascade', readonly=True, index=True,
    )

    # --- recordatorio a la agencia ---

    def _enqueue_agency_reminder(self, order, email_to, signer):
        order.ensure_one()
        if self.search_count([('sale_order_id', '=', order.id), ('kind', '=', 'agency_reminder'),
                              ('state', '!=', 'error')]):
            return self.browse()
        subject, body = order._agency_reminder_content(signer)
        return self.create({
            'kind': 'agency_reminder', 'sale_order_id': order.id, 'recipient_email': email_to,
            'subject': subject, 'body': body,
            'reason': _('Sin respuesta; servicio en %s días') % order.restagrup_days_to_service,
        })

    def _still_applies_agency_reminder(self):
        order = self.sale_order_id
        return order.state == 'sent' and not order.restagrup_agency_reminder_date

    def _send_agency_reminder(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.sale_order_id._post_agency_reminder(self.subject, self.body, self.recipient_email)

    # --- grupo cancelado ---

    def _enqueue_group_cancelled(self, line):
        """Aviso de cancelación al restaurante de una petición abierta, con la plantilla «El grupo no sale»."""
        line.ensure_one()
        template = self.env.ref('restagrup_service_orders.notice_template_group_not_going')
        wizard_line = self._notice_wizard_line(line)
        values = wizard_line._placeholder_values()
        subject, body = template.subject, html2plaintext(template.body).strip()
        for key, value in values.items():
            subject, body = subject.replace(key, value), body.replace(key, value)
        return self.create({
            'kind': 'group_cancelled', 'line_id': line.id,
            'recipient_email': (line.partner_id.email or '').strip(),
            'subject': subject, 'body': body, 'reason': _('El grupo no sale'),
        })

    def _notice_wizard_line(self, line):
        wizard = self.env['restagrup.restaurant.notice.wizard'].create({
            'lead_id': line.search_id.lead_id.id,
            'line_ids': [(0, 0, {
                'restaurant_id': line.partner_id.id,
                'event_label': line.search_id._event_label() or line.search_id.display_name,
                'search_line_id': line.id,
            })],
        })
        return wizard.line_ids

    def _still_applies_group_cancelled(self):
        return self.line_id.etiqueta == 'cancelado'

    def _send_group_cancelled(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        body_html = Markup('<br/>').join(Markup.escape(l) for l in self.body.splitlines())
        # El aviso sale con el mecanismo de «Avisar a restaurantes»: queda en «Avisos enviados».
        self._notice_wizard_line(self.line_id)._send_notice(self.subject, str(body_html))
