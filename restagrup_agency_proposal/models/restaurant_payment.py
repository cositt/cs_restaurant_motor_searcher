# -*- coding: utf-8 -*-
"""F5: el pago a cada restaurante. Se le pide la cuenta si no la tenemos (con la proforma), a las 48 h toca pagarle
y, hecha la transferencia, se le manda el justificante con nuestros datos fiscales.

Respuesta de Conchita (2026-11-09): lo que toca pagar en fin de semana se paga el viernes (los grupos del lunes y
del martes); y cada restaurante tiene su condición: 48 h antes, pago inmediato o señal (50 %) + resto 48 h antes."""
import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext
from odoo.tools.misc import format_amount

from odoo.addons.restagrup_restaurants.models.restaurant_menu_ai import _attachment_text

from .payment_dates import DEFAULT_DEPOSIT_PERCENT, PAYMENT_TERMS, restaurant_payment_due_date

_logger = logging.getLogger(__name__)

CONFIRMATION_REPORT = 'restagrup_agency_proposal.report_restaurant_confirmation'
CHATTER_LANG = 'es_ES'
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


class ResPartner(models.Model):
    _inherit = 'res.partner'

    restagrup_payment_terms = fields.Selection(
        PAYMENT_TERMS, string='Condición de pago', default='standard', required=True,
        help='Cuándo se le paga a este restaurante. Algunos piden pago inmediato o una señal para guardar la reserva.')
    restagrup_deposit_percent = fields.Float(
        string='Señal (%)', default=DEFAULT_DEPOSIT_PERCENT, help='Parte que se paga al confirmar; el resto, 48 h antes.')


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
    restagrup_payment_terms = fields.Selection(
        related='partner_id.commercial_partner_id.restagrup_payment_terms', string='Condición de pago')
    restagrup_deposit_amount = fields.Monetary(
        string='Señal', compute='_compute_restagrup_amounts', currency_field='currency_id')
    restagrup_deposit_paid = fields.Boolean(string='Señal pagada', copy=False, tracking=True)
    restagrup_deposit_paid_date = fields.Datetime(string='Fecha de la señal', copy=False, readonly=True)
    restagrup_deposit_paid_amount = fields.Monetary(
        string='Señal pagada (importe)', copy=False, readonly=True, currency_field='currency_id')
    restagrup_amount_to_pay = fields.Monetary(
        string='Queda por pagar', compute='_compute_restagrup_amounts', currency_field='currency_id',
        help='Total de la hoja menos la señal ya pagada.')
    restagrup_payment_due_date = fields.Date(
        string='Toca pagar el', compute='_compute_restagrup_payment_due_date',
        help='48 h antes del servicio (en fin de semana, el viernes antes). Con pago inmediato o señal pendiente: ya.')

    @api.depends('amount_total', 'partner_id.commercial_partner_id.restagrup_payment_terms',
                 'partner_id.commercial_partner_id.restagrup_deposit_percent', 'restagrup_deposit_paid_amount',
                 'restagrup_restaurant_paid')
    def _compute_restagrup_amounts(self):
        for sheet in self:
            restaurant = sheet.partner_id.commercial_partner_id
            sheet.restagrup_deposit_amount = (
                sheet.amount_total * restaurant.restagrup_deposit_percent / 100.0
                if restaurant.restagrup_payment_terms == 'deposit' else 0.0)
            sheet.restagrup_amount_to_pay = (
                0.0 if sheet.restagrup_restaurant_paid else sheet.amount_total - sheet.restagrup_deposit_paid_amount)

    @api.depends('restagrup_service_date', 'restagrup_payment_terms', 'restagrup_deposit_paid', 'create_date')
    def _compute_restagrup_payment_due_date(self):
        hours = self.env['restagrup.payment.settings'].value('restaurant_payment_hours')
        for sheet in self:
            pay_now = (sheet.restagrup_payment_terms == 'immediate'
                       or (sheet.restagrup_payment_terms == 'deposit' and not sheet.restagrup_deposit_paid))
            if pay_now:
                sheet.restagrup_payment_due_date = fields.Date.context_today(
                    sheet, sheet.create_date or fields.Datetime.now())
            else:
                sheet.restagrup_payment_due_date = restaurant_payment_due_date(sheet.restagrup_service_date, hours)

    @api.depends('order_line.restagrup_sale_line_id.service_date')
    def _compute_restagrup_service_date(self):
        for sheet in self:
            dates = [d for d in sheet.order_line.mapped('restagrup_sale_line_id.service_date') if d]
            sheet.restagrup_service_date = min(dates) if dates else False

    @api.depends('partner_id.commercial_partner_id.bank_ids')
    def _compute_restagrup_has_bank(self):
        for sheet in self:
            sheet.restagrup_has_bank = bool(sheet.partner_id.commercial_partner_id.bank_ids)

    # --- texto de la cuenta en la confirmación al restaurante (notas de Conchita 05/11) ---

    def _restagrup_restaurant_iban(self):
        self.ensure_one()
        restaurant = self.partner_id.commercial_partner_id
        number = restaurant.bank_ids[:1].acc_number or restaurant.restaurant_iban or ''
        return re.sub(r'\s+', '', number).upper()

    def _restagrup_when_we_pay_text(self, hours):
        """Cuándo se le paga, según la condición de su ficha."""
        restaurant = self.partner_id.commercial_partner_id
        if restaurant.restagrup_payment_terms == 'immediate':
            return _('a la confirmación de la reserva')
        if restaurant.restagrup_payment_terms == 'deposit':
            return _('con una señal del %(pct)s %% a la confirmación de la reserva y el resto con un mínimo de'
                     ' %(hours)s h de antelación') % {'pct': '%g' % restaurant.restagrup_deposit_percent, 'hours': hours}
        return _('con un mínimo de %s h de antelación') % hours

    def restagrup_restaurant_bank_text(self):
        """Con su cuenta: a qué cuenta se le paga y que avise si ha cambiado. Sin ella: que nos la mande."""
        self.ensure_one()
        hours = int(self.env['restagrup.payment.settings'].value('restaurant_payment_hours') or 48)
        when = self._restagrup_when_we_pay_text(hours)
        iban = self._restagrup_restaurant_iban()
        if not iban:
            if self.partner_id.commercial_partner_id.restagrup_payment_terms == 'standard':
                when = _('%s h antes del servicio') % hours
            return _('Quedamos a la espera de recibir su número de cuenta para poder realizar el pago %s.') % when
        grouped = ' '.join(iban[i:i + 4] for i in range(0, len(iban), 4))
        return _('El prepago se realizará %(when)s al número de cuenta %(iban)s; si ha cambiado, por favor'
                 ' indíquenoslo.') % {'when': when, 'iban': grouped}

    # --- cron ---

    @api.model
    def _cron_restaurant_payments(self):
        """Cron diario: marca «Toca pagar» el día que toca (ver `restagrup_payment_due_date`) y, dentro del plazo de
        pago a la agencia, pide la cuenta a quien no la tenga."""
        today = fields.Date.context_today(self)
        request_limit = today + timedelta(days=self.env['restagrup.payment.settings'].value('payment_request_days'))
        sheets = self.search([
            ('state', '!=', 'cancel'), ('restagrup_sale_order_id', '!=', False),
            ('restagrup_restaurant_paid', '=', False), ('restagrup_service_date', '>=', today),
        ])
        for sheet in sheets:
            due = bool(sheet.restagrup_payment_due_date) and today >= sheet.restagrup_payment_due_date
            if due != sheet.restagrup_payment_due:
                sheet.restagrup_payment_due = due
            if sheet.restagrup_has_bank or sheet.restagrup_bank_request_date \
                    or sheet.restagrup_service_date > request_limit:
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
            email_add_signature=False,  # el texto ya lleva {firma}
            outgoing_email_to=email_to, attachments=[self._restagrup_proforma()],
        )
        self.write({'restagrup_bank_request_date': fields.Datetime.now()})

    # --- la cuenta que contesta el restaurante ---

    def _restagrup_classify_response(self, msg_dict):
        """La respuesta con la cuenta es la de la petición de cuenta, no la de la hoja: no se clasifica."""
        if self._restagrup_read_bank_account(msg_dict):
            return False
        return super()._restagrup_classify_response(msg_dict)

    def _restagrup_read_bank_account(self, msg_dict):
        """Si le pedimos la cuenta y contesta con un IBAN, se guarda en su ficha si es válido. Sin IA: se comprueba.
        True si la respuesta traía la cuenta."""
        self.ensure_one()
        if not self.restagrup_bank_request_date or self.restagrup_has_bank:
            return False
        raw_body = msg_dict.get('body') or ''
        text = '\n'.join([html2plaintext(raw_body) if raw_body else '', _attachment_text(msg_dict.get('attachments'))])
        iban, valid = _find_iban(text)
        if not iban:
            return False
        if not valid:
            self.message_post(body=_('El restaurante ha mandado una cuenta (%s) que no es válida: revísala con él.')
                              % _masked(iban))
            return True
        # En español: Odoo deja en la ficha «Cuenta bancaria creada» en el idioma del contexto, y el buzón no tiene.
        self.env['res.partner.bank'].sudo().with_context(lang=CHATTER_LANG).create({
            'partner_id': self.partner_id.commercial_partner_id.id, 'acc_number': iban})
        self.message_post(body=_('Cuenta bancaria guardada en la ficha de %(name)s: %(iban)s.') % {
            'name': self.partner_id.name, 'iban': _masked(iban)})
        return True

    # --- pagar y mandar el justificante ---

    def _restagrup_money(self, amount):
        return format_amount(self.env, amount, self.currency_id)

    def action_mark_deposit_paid(self):
        for sheet in self:
            if sheet.restagrup_payment_terms != 'deposit' or sheet.restagrup_deposit_paid:
                continue
            deposit = sheet.restagrup_deposit_amount
            sheet.write({'restagrup_deposit_paid': True, 'restagrup_deposit_paid_date': fields.Datetime.now(),
                         'restagrup_deposit_paid_amount': deposit, 'restagrup_payment_due': False})
            sheet.message_post(body=_('Señal pagada: %(deposit)s. Queda por pagar: %(rest)s.') % {
                'deposit': sheet._restagrup_money(deposit), 'rest': sheet._restagrup_money(sheet.restagrup_amount_to_pay)})

    def action_unmark_deposit_paid(self):
        for sheet in self.filtered('restagrup_deposit_paid'):
            sheet.write({'restagrup_deposit_paid': False, 'restagrup_deposit_paid_date': False,
                         'restagrup_deposit_paid_amount': 0.0})
            sheet.message_post(body=_('Señal desmarcada.'))

    def action_mark_restaurant_paid(self):
        rests = {sheet.id: sheet.restagrup_amount_to_pay for sheet in self}
        res = super().action_mark_restaurant_paid()
        self.write({'restagrup_payment_due': False})
        for sheet in self.filtered('restagrup_deposit_paid'):
            sheet.message_post(body=_('Pagado el resto: %(rest)s (señal de %(deposit)s ya descontada).') % {
                'rest': sheet._restagrup_money(rests[sheet.id]),
                'deposit': sheet._restagrup_money(sheet.restagrup_deposit_paid_amount)})
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
                'default_subject': subject, 'default_email_add_signature': False,  # el texto ya lleva {firma}
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

    @api.depends('lead_id', 'request_lead_id', 'sale_order_id.opportunity_id',
                 'purchase_order_id.restagrup_sale_order_id.opportunity_id')
    def _compute_group_id(self):
        super()._compute_group_id()
        for mail in self.filtered(lambda m: not m.group_id):
            mail.group_id = mail.sudo().purchase_order_id.restagrup_sale_order_id.opportunity_id

    @api.depends('line_id.name', 'line_id.partner_id.name', 'purchase_order_id.partner_id.name')
    def _compute_restaurant_name(self):
        super()._compute_restaurant_name()
        for mail in self.filtered(lambda m: not m.restaurant_name):
            mail.restaurant_name = mail.sudo().purchase_order_id.partner_id.name or False

    def _still_applies_restaurant_bank_request(self):
        sheet = self.purchase_order_id
        return bool(sheet.state != 'cancel' and not sheet.restagrup_restaurant_paid and not sheet.restagrup_has_bank
                    and not sheet.restagrup_bank_request_date)

    def _send_restaurant_bank_request(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.purchase_order_id._restagrup_post_bank_request(self.subject, self.body, self.recipient_email)
