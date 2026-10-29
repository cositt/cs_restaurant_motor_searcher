# -*- coding: utf-8 -*-
"""F5: el pago a cada restaurante. Se le pide la cuenta si no la tenemos (con la proforma), a las 48 h toca pagarle
y, hecha la transferencia, se le manda el justificante con nuestros datos fiscales."""
import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.restagrup_restaurants.models.restaurant_menu_ai import _attachment_text

_logger = logging.getLogger(__name__)

CONFIRMATION_REPORT = 'restagrup_agency_proposal.report_restaurant_confirmation'
IBAN_CANDIDATE_RE = re.compile(r'\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){10,30}')
# Longitud del IBAN por país (los habituales); con ella se corta lo que va pegado detrás.
IBAN_LENGTHS = {'ES': 24, 'PT': 25, 'FR': 27, 'IT': 27, 'DE': 22, 'GB': 22, 'NL': 18, 'BE': 16, 'AD': 24, 'IE': 22}


def _iban_is_valid(iban):
    """Comprobación ISO 13616 (módulo 97)."""
    if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{10,30}', iban):
        return False
    digits = ''.join(str(int(char, 36)) for char in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def _find_iban(text):
    """(iban, válido) del primer IBAN que aparece en el texto, o (None, False)."""
    for match in IBAN_CANDIDATE_RE.finditer((text or '').upper()):
        compact = match.group(0).replace(' ', '')
        length = IBAN_LENGTHS.get(compact[:2])
        if length:
            if len(compact) < length:
                continue
            compact = compact[:length]
        return compact, _iban_is_valid(compact)
    return None, False


def _masked(iban):
    return '%s **** %s' % (iban[:4], iban[-4:])


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    restagrup_service_date = fields.Date(
        string='Fecha del servicio', compute='_compute_restagrup_service_date', store=True,
        help='Primer servicio de este restaurante en el grupo.')
    restagrup_bank_request_date = fields.Datetime(string='Cuenta pedida al restaurante', copy=False, readonly=True)
    restagrup_payment_due = fields.Boolean(
        string='Toca pagar', copy=False, readonly=True, index=True,
        help='Se ha llegado al plazo de pago al restaurante (48 h antes del servicio, en Ajustes) y no está pagado.')
    restagrup_payment_receipt_sent_date = fields.Datetime(
        string='Justificante enviado al restaurante', copy=False, readonly=True)
    restagrup_has_bank = fields.Boolean(string='Tenemos su cuenta', compute='_compute_restagrup_has_bank')

    @api.depends('order_line.restagrup_sale_line_id.service_date')
    def _compute_restagrup_service_date(self):
        for sheet in self:
            dates = [d for d in sheet.order_line.mapped('restagrup_sale_line_id.service_date') if d]
            sheet.restagrup_service_date = min(dates) if dates else False

    @api.depends('partner_id.commercial_partner_id.bank_ids')
    def _compute_restagrup_has_bank(self):
        for sheet in self:
            sheet.restagrup_has_bank = bool(sheet.partner_id.commercial_partner_id.bank_ids)

    # --- cron ---

    @api.model
    def _cron_restaurant_payments(self):
        """Cron diario: dentro del plazo de pago a la agencia pide la cuenta a quien no la tenga; a las 48 h marca
        «Toca pagar»."""
        today = fields.Date.context_today(self)
        settings = self.env['restagrup.payment.settings']
        due_limit = timedelta(hours=settings.value('restaurant_payment_hours'))
        sheets = self.search([
            ('state', '!=', 'cancel'), ('restagrup_sale_order_id', '!=', False),
            ('restagrup_restaurant_paid', '=', False), ('restagrup_service_date', '>=', today),
            ('restagrup_service_date', '<=', today + timedelta(days=settings.value('payment_request_days'))),
        ])
        for sheet in sheets:
            due = today >= sheet.restagrup_service_date - due_limit
            if due != sheet.restagrup_payment_due:
                sheet.restagrup_payment_due = due
            if sheet.restagrup_has_bank or sheet.restagrup_bank_request_date:
                continue
            try:
                with self.env.cr.savepoint():
                    sheet._restagrup_ask_bank_account()
            except Exception:  # noqa: BLE001 -- una hoja rota no debe parar al resto
                _logger.exception('Petición de cuenta fallida para %s', sheet.name)

    # --- pedir la cuenta ---

    def _restagrup_mail_values(self, signer):
        self.ensure_one()
        sale_lines = self.order_line.mapped('restagrup_sale_line_id').sorted(
            lambda l: (l.service_date or fields.Date.today(), l.service_hour or 0.0))
        hour = sale_lines[:1].service_hour
        company = self.company_id
        tax_data = [company.name or '']
        if company.vat:
            tax_data.append(_('CIF: %s') % company.vat)
        tax_data += [company.street or '', ' '.join(filter(None, [company.zip, company.city]))]
        return {
            'restaurante': self.partner_id.name or '', 'pedido': self.name,
            'grupo': self.restagrup_sale_order_id.opportunity_id.name or self.restagrup_sale_order_id.name or '',
            'fecha': self.restagrup_service_date.strftime('%d/%m/%Y') if self.restagrup_service_date else '',
            'hora': '%02d:%02d' % divmod(round(hour * 60), 60) if hour else '',
            'ciudad': (self.partner_id.city or '').upper(),
            'datos_fiscales': '\n'.join(line for line in tax_data if line.strip()), 'firma': signer,
        }

    def _restagrup_signer(self):
        order = self.restagrup_sale_order_id
        return order.user_id.name or self.env.company.name

    def _restagrup_bank_request_content(self):
        values = self._restagrup_mail_values(self._restagrup_signer())

        def fallback():
            return (_('Número de cuenta para el prepago — %s') % values['grupo'], '\n'.join([
                _('Buenos días,'), '',
                _('Debido a la proximidad de la fecha de servicio, necesitamos recibir el numero de cuenta al que'
                  ' realizar el prepago de este grupo. Adjunto de nuevo proforma con todos los detalles de la reserva.'),
                '', _('Quedamos a la espera,'), _('Gracias.'), values['firma']]))

        return self.env['restagrup.mail.template']._compose('restaurant_bank_request', values, fallback)

    def _restagrup_ask_bank_account(self):
        self.ensure_one()
        queue = self.env['restagrup.pending.mail']
        if queue.search_count([('purchase_order_id', '=', self.id), ('kind', '=', 'restaurant_bank_request'),
                               ('state', '=', 'pending')]):
            return
        email_to = (self.partner_id.email or '').strip()
        if not email_to:
            _logger.warning('Hoja %s sin email del restaurante: no se le pide la cuenta.', self.name)
            return
        subject, body = self._restagrup_bank_request_content()
        if queue._is_automatic('restaurant_bank_request'):
            self._restagrup_post_bank_request(subject, body, email_to)
            return
        queue.create({
            'kind': 'restaurant_bank_request', 'purchase_order_id': self.id, 'recipient_email': email_to,
            'subject': subject, 'body': body,
            'reason': _('Servicio el %s y sin cuenta bancaria') % self.restagrup_service_date.strftime('%d/%m/%Y'),
        })

    def _restagrup_proforma(self):
        pdf, _kind = self.env['ir.actions.report']._render_qweb_pdf(CONFIRMATION_REPORT, self.ids)
        return 'Confirmacion-Restaurante-%s.pdf' % (self.restagrup_sale_order_id.name or self.name), pdf

    def _restagrup_post_bank_request(self, subject, body_text, email_to):
        """Sale por el hilo de la hoja con la proforma; la respuesta con la cuenta vuelve aquí."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(
                self.restagrup_sale_order_id.user_id.email or self.env.user.email),
            outgoing_email_to=email_to, attachments=[self._restagrup_proforma()],
        )
        self.write({'restagrup_bank_request_date': fields.Datetime.now()})

    # --- la cuenta que contesta el restaurante ---

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for sheet in self:
            sheet._restagrup_read_bank_account(msg_dict)
        return res

    def _restagrup_read_bank_account(self, msg_dict):
        """Si le pedimos la cuenta y contesta con un IBAN válido, se guarda en su ficha. Sin IA: se comprueba."""
        self.ensure_one()
        if not self.restagrup_bank_request_date or self.restagrup_has_bank:
            return
        raw_body = msg_dict.get('body') or ''
        text = '\n'.join([html2plaintext(raw_body) if raw_body else '', _attachment_text(msg_dict.get('attachments'))])
        iban, valid = _find_iban(text)
        if not iban:
            return
        if not valid:
            self.message_post(body=_('El restaurante ha mandado una cuenta (%s) que no es válida: revísala con él.')
                              % _masked(iban))
            return
        self.env['res.partner.bank'].sudo().create({
            'partner_id': self.partner_id.commercial_partner_id.id, 'acc_number': iban})
        self.message_post(body=_('Cuenta bancaria guardada en la ficha de %(name)s: %(iban)s.') % {
            'name': self.partner_id.name, 'iban': _masked(iban)})

    # --- pagar y mandar el justificante ---

    def action_mark_restaurant_paid(self):
        res = super().action_mark_restaurant_paid()
        self.write({'restagrup_payment_due': False})
        return res

    def action_send_payment_receipt(self):
        """Correo al restaurante con la confirmación de reserva adjunta: la persona añade la transferencia y envía."""
        self.ensure_one()
        if not self.restagrup_restaurant_paid:
            raise UserError(_('Marca antes la transferencia como hecha.'))
        values = self._restagrup_mail_values(self._restagrup_signer())

        def fallback():
            return (_('Transferencia y confirmación de reserva — %s') % values['grupo'], '\n'.join([
                _('Hola %s.') % values['restaurante'], '',
                _('Adjunto transferencia y confirmación de reserva del grupo %(grupo)s.') % values, '',
                _('Nuestros datos fiscales para la factura son:'), values['datos_fiscales'], '',
                _('Enviar factura únicamente por email.'), '', _('Un saludo y gracias!'), values['firma']]))

        subject, body = self.env['restagrup.mail.template']._compose('restaurant_payment_receipt', values, fallback)
        name, pdf = self._restagrup_proforma()
        attachment = self.env['ir.attachment'].create({
            'name': name, 'raw': pdf, 'mimetype': 'application/pdf', 'res_model': 'mail.compose.message', 'res_id': 0,
        })
        return {
            'type': 'ir.actions.act_window', 'name': _('Enviar justificante al restaurante'),
            'res_model': 'mail.compose.message', 'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new',
            'context': {
                'default_model': self._name, 'default_res_ids': self.ids, 'default_composition_mode': 'comment',
                'default_partner_ids': self.partner_id.ids, 'default_attachment_ids': attachment.ids,
                'default_subject': subject,
                'default_body': Markup('<br/>').join(Markup.escape(line) for line in body.splitlines()),
                'default_email_from': self.env['restagrup.system.mail'].email_from(
                    self.restagrup_sale_order_id.user_id.email_formatted or self.env.user.email_formatted),
                'restagrup_payment_receipt': True,
            },
        }

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if self.env.context.get('restagrup_payment_receipt'):
            self.write({'restagrup_payment_receipt_sent_date': fields.Datetime.now()})
        return message


class RestagrupPendingMail(models.Model):
    _inherit = 'restagrup.pending.mail'

    kind = fields.Selection(selection_add=[
        ('restaurant_bank_request', 'Cuenta bancaria del restaurante'),
    ], ondelete={'restaurant_bank_request': 'cascade'})
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Hoja de servicio', ondelete='cascade', readonly=True, index=True)
    # Guardado: el aviso del comercial no tiene que leer la hoja de compra (puede no tener permiso de compras).
    sheet_owner_id = fields.Many2one(
        related='purchase_order_id.restagrup_sale_order_id.user_id', string='Responsable de la hoja', store=True)

    def _still_applies_restaurant_bank_request(self):
        sheet = self.purchase_order_id
        return bool(sheet.state != 'cancel' and not sheet.restagrup_restaurant_paid and not sheet.restagrup_has_bank
                    and not sheet.restagrup_bank_request_date)

    def _send_restaurant_bank_request(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.purchase_order_id._restagrup_post_bank_request(self.subject, self.body, self.recipient_email)
