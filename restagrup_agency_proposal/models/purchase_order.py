# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _get_edi_builders(self):
        """Sin «Conecte con su software» en el portal: la facturación electrónica no aplica a los restaurantes."""
        return []

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

    # --- confirmación al restaurante por correo (ronda de ajustes 09/11) ---

    def _restagrup_confirmation_content(self):
        self.ensure_one()
        order = self.restagrup_sale_order_id
        signer = order.user_id.name or self.env.company.name
        values = {
            'restaurante': self.partner_id.name or '', 'pedido': order.name or self.name,
            'grupo': order.opportunity_id.name or order.name or '',
            'servicios': self._restagrup_service_lines_text(), 'firma': signer,
        }

        def fallback():
            return (_('Confirmación de reserva %(pedido)s — %(grupo)s') % values, '\n'.join([
                _('Hola %s,') % values['restaurante'], '',
                _('Os confirmamos que finalmente realizamos la reserva del grupo %s con vosotros:') % values['grupo'],
                '', values['servicios'], '',
                _('Adjuntamos la confirmación en PDF. Por favor, respondednos a este correo con vuestro OK.'), '',
                _('¡Gracias!'), signer]))

        return self.env['restagrup.mail.template']._compose('restaurant_confirmation', values, fallback)

    def action_send_confirmation_restaurant(self):
        """Envía la confirmación de la reserva al restaurante, con su PDF, por el hilo de la hoja: su OK vuelve
        aquí. Antes de enviarla el cortafuegos comprueba que todo cuadra."""
        return self._restagrup_gated('confirm_restaurant', '_restagrup_do_send_confirmation_restaurant')

    def _restagrup_do_send_confirmation_restaurant(self):
        for sheet in self:
            email_to = (sheet.partner_id.email or '').strip()
            if not email_to:
                raise UserError(_('%s no tiene email: añádeselo o descarga la confirmación y envíasela a mano.')
                                % sheet.partner_id.name)
            subject, body_text = sheet._restagrup_confirmation_content()
            order = sheet.restagrup_sale_order_id
            sheet.message_post(
                body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
                subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
                email_from=self.env['restagrup.system.mail'].email_from(order.user_id.email or self.env.user.email),
                email_add_signature=False, outgoing_email_to=email_to,
                attachments=[sheet._restagrup_proforma()],
            )
            note = _('Confirmación de reserva enviada a %(name)s (%(email)s).') % {
                'name': sheet.partner_id.name, 'email': email_to}
            order._restagrup_log_on_searches(note)
            if order.opportunity_id:
                order.opportunity_id.message_post(body=note)
        return True
