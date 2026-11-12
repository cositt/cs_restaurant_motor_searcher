# -*- coding: utf-8 -*-
"""El expediente con sus documentos a mano (ronda de ajustes 09/11).

Conchita pedía, desde el expediente y sin ir al pedido: enviar la confirmación a la agencia (queda confirmada la
reserva; que completen los datos, elijan menú, contacto del guía, intolerancias), descargar la confirmación de la
agencia, la del restaurante y el bono, y enviar la confirmación a los restaurantes."""
from markupsafe import Markup

from odoo import _, models
from odoo.exceptions import UserError

AGENCY_REPORT = 'restagrup_agency_proposal.action_report_booking_confirmation'
RESTAURANT_REPORT = 'restagrup_agency_proposal.action_report_restaurant_confirmation'


class SaleOrderAgencyConfirmation(models.Model):
    _inherit = 'sale.order'

    def _restagrup_agency_confirmation_content(self):
        self.ensure_one()
        signer = self.user_id.name or self.env.company.name
        values = {
            'agencia': self.partner_id.commercial_partner_id.name or self.partner_id.name or '',
            'pedido': self.name, 'grupo': self.opportunity_id.name or self.name, 'firma': signer,
        }

        def fallback():
            return (_('Confirmación de reserva %(pedido)s — %(grupo)s') % values, '\n'.join([
                _('Hola %s,') % values['agencia'], '',
                _('Os confirmamos que queda confirmada la reserva del grupo %s. Adjuntamos la confirmación en PDF'
                  ' con todos los servicios.') % values['grupo'], '',
                _('Para dejarlo todo listo, por favor, completad lo que falte:'),
                _('- El menú elegido en cada servicio (si aún no lo habéis elegido).'),
                _('- Nombre y móvil de contacto del guía o responsable del grupo.'),
                _('- Alergias e intolerancias de los comensales.'),
                _('- El número final de comensales, en cuanto lo tengáis.'), '',
                _('¡Gracias!'), signer]))

        return self.env['restagrup.mail.template']._compose('agency_confirmation', values, fallback)

    def action_send_confirmation_agency(self):
        """Confirmación a la agencia por correo, con su PDF. Antes, el cortafuegos comprueba que todo cuadra."""
        return self._restagrup_gated('confirm_agency', '_restagrup_do_send_confirmation_agency')

    def _restagrup_do_send_confirmation_agency(self):
        """Reunión 12/11 (7.6/3.8): abre «Revisar y enviar» con el texto y el PDF; a la agencia y/o sus contactos."""
        order = self[:1]
        chain = list(self.env.context.get('restagrup_send_chain') or []) + self[1:].ids
        order._restagrup_default_send_emails()
        subject, body_text = order._restagrup_agency_confirmation_content()
        pdf, _kind = self.env['ir.actions.report']._render_qweb_pdf(AGENCY_REPORT, order.ids)
        wizard = self.env['restagrup.send.wizard']
        return wizard.with_context(restagrup_send_chain=chain)._open_for(
            order, subject, body_text, partner=order.partner_id.commercial_partner_id,
            title=_('Confirmación a la agencia'),
            attachments=wizard._draft_attachment('Confirmacion-Agencia-%s.pdf' % order.name, pdf),
            chain_method='action_send_confirmation_agency')

    def _restagrup_default_send_emails(self):
        self.ensure_one()
        email = (self.partner_id.email or '').strip()
        if not email:
            raise UserError(_('La agencia %s no tiene email: añádeselo o descarga la confirmación y envíasela'
                              ' a mano.') % self.partner_id.name)
        return [email]

    def _restagrup_send_reviewed(self, subject, body_text, emails, attachments=None):
        self.ensure_one()
        email_to = ', '.join(emails)
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(self.user_id.email or self.env.user.email),
            email_add_signature=False, outgoing_email_to=email_to,
            attachment_ids=attachments.ids if attachments else [],
        )
        note = _('Confirmación de reserva enviada a la agencia (%s).') % email_to
        self._restagrup_log_on_searches(note)
        if self.opportunity_id:
            self.opportunity_id._restagrup_note_proforma_sent()
            self.opportunity_id.message_post(body=note)
        return True


class CrmLeadDocuments(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_heal_missing_order(self):
        """Si pasó a expediente sin pedido (antes de la ronda del 09/11) y ya tiene restaurante elegido, el pedido
        se crea ahora (ronda de ajustes 11/11: el grupo de Rubén). Devuelve la acción del paso que falte (confirmar
        un precio, elegir menú) o None."""
        self.ensure_one()
        if self.restagrup_stage_key != 'expediente' or self._restagrup_live_orders():
            return None
        return self._restagrup_prepare_order_for_file()

    def _restagrup_quote_order_for_agency(self):
        """Reunión 12/11 (7.3/8.4): en Presupuesto la confirmación a la agencia puede salir antes de que el
        restaurante confirme (sus menús ya están en la ficha). Sin pedido se crea el presupuesto conjunto, sin
        confirmarlo y sin cambiar de fase. Devuelve la acción del paso que falte (elegir menú...) o None."""
        self.ensure_one()
        if self.restagrup_stage_key != 'presupuesto' or self._restagrup_live_orders():
            return None
        result = self.action_create_joint_quote()
        return None if self._restagrup_live_orders() else result

    def _restagrup_file_orders(self):
        self.ensure_one()
        orders = self._restagrup_live_orders()
        if not orders:
            raise UserError(_('Este grupo aún no tiene pedido: elige el restaurante de cada servicio y'
                              ' pásalo a expediente.'))
        return orders

    def _restagrup_file_sheets(self):
        sheets = self._restagrup_file_orders().sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')
        if not sheets:
            raise UserError(_('Todavía no hay hojas de restaurante para este grupo.'))
        return sheets.with_env(self.env)

    def action_send_agency_confirmation(self):
        pending = self._restagrup_heal_missing_order() or self._restagrup_quote_order_for_agency()
        if pending:
            return pending
        orders = self._restagrup_file_orders()
        return orders[:1].with_context(restagrup_send_chain=orders[1:].ids).action_send_confirmation_agency()

    def action_download_agency_confirmation(self):
        pending = self._restagrup_heal_missing_order()
        if pending:
            return pending
        orders = self._restagrup_file_orders()
        return self.env.ref(AGENCY_REPORT).report_action(orders)

    def action_download_restaurant_confirmation(self):
        pending = self._restagrup_heal_missing_order()
        if pending:
            return pending
        return self.env.ref(RESTAURANT_REPORT).report_action(self._restagrup_file_sheets())

    def action_download_voucher(self):
        pending = self._restagrup_heal_missing_order()
        if pending:
            return pending
        orders = self._restagrup_file_orders()
        for order in orders:
            order._restagrup_check_paid()
        return self.env.ref('restagrup_agency_proposal.action_report_booking_voucher').report_action(orders)

    def action_send_restaurant_confirmations(self):
        pending = self._restagrup_heal_missing_order()
        if pending:
            return pending
        sheets = self._restagrup_file_sheets().sorted('id')
        # Reunión 12/11 (7.6): una ventana «Revisar y enviar» por restaurante, una detrás de otra.
        return sheets[:1].with_context(restagrup_send_chain=sheets[1:].ids).action_send_confirmation_restaurant()
