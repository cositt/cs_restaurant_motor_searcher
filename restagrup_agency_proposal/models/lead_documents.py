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
        for order in self:
            email_to = (order.partner_id.email or '').strip()
            if not email_to:
                raise UserError(_('La agencia %s no tiene email: añádeselo o descarga la confirmación y envíasela'
                                  ' a mano.') % order.partner_id.name)
            subject, body_text = order._restagrup_agency_confirmation_content()
            pdf, _kind = self.env['ir.actions.report']._render_qweb_pdf(AGENCY_REPORT, order.ids)
            order.message_post(
                body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
                subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
                email_from=self.env['restagrup.system.mail'].email_from(order.user_id.email or self.env.user.email),
                email_add_signature=False, outgoing_email_to=email_to,
                attachments=[('Confirmacion-Agencia-%s.pdf' % order.name, pdf)],
            )
            note = _('Confirmación de reserva enviada a la agencia (%s).') % email_to
            order._restagrup_log_on_searches(note)
            if order.opportunity_id:
                order.opportunity_id._restagrup_note_proforma_sent()
                order.opportunity_id.message_post(body=note)
        return True


class CrmLeadDocuments(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_file_orders(self):
        self.ensure_one()
        orders = self._restagrup_live_orders()
        if not orders:
            raise UserError(_('Este grupo aún no tiene pedido: pásalo a expediente con el restaurante elegido.'))
        return orders

    def _restagrup_file_sheets(self):
        sheets = self._restagrup_file_orders().sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')
        if not sheets:
            raise UserError(_('Todavía no hay hojas de restaurante para este grupo.'))
        return sheets.with_env(self.env)

    def action_send_agency_confirmation(self):
        for order in self._restagrup_file_orders():
            result = order.action_send_confirmation_agency()
            if isinstance(result, dict):
                return result
        return True

    def action_download_agency_confirmation(self):
        orders = self._restagrup_file_orders()
        return self.env.ref(AGENCY_REPORT).report_action(orders)

    def action_download_restaurant_confirmation(self):
        return self.env.ref(RESTAURANT_REPORT).report_action(self._restagrup_file_sheets())

    def action_download_voucher(self):
        orders = self._restagrup_file_orders()
        for order in orders:
            order._restagrup_check_paid()
        return self.env.ref('restagrup_agency_proposal.action_report_booking_voucher').report_action(orders)

    def action_send_restaurant_confirmations(self):
        for sheet in self._restagrup_file_sheets():
            result = sheet.action_send_confirmation_restaurant()
            if isinstance(result, dict):
                return result
        return True
