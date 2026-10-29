# -*- coding: utf-8 -*-
"""F4: el pago de la agencia. Se pide a los 7 días, se reclama a las 72 h y el justificante que manda lo lee la IA;
marcarlo pagado lo hace siempre una persona."""
import logging
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.restagrup_restaurants.models.restaurant_menu_ai import _attachment_text, _number

_logger = logging.getLogger(__name__)

# Tipo de correo -> campo con la fecha en que salió (uno de cada por pedido).
PAYMENT_KINDS = {
    'agency_payment_request': 'restagrup_payment_requested_date',
    'agency_payment_urgent': 'restagrup_payment_urgent_date',
}
# Lo que antes se escribía en Ajustes y su texto de serie (si sigue el de serie no se importa nada).
LEGACY_PAYMENT_TEXTS = {
    'agency_payment_request': ('restagrup.payment_request_text', (
        'Hola {agencia}, se acerca la fecha de vuestro servicio. Os pedimos que nos enviéis la transferencia del '
        '100 % de la reserva y el justificante de pago para poder emitir el bono de agencia. Los datos bancarios '
        'están en la confirmación de reserva. Gracias.')),
    'agency_payment_urgent': ('restagrup.payment_urgent_text', (
        'Hola {agencia}, debido a la proximidad del servicio necesitamos recibir el justificante de pago para '
        'poder enviaros el bono de agencia.')),
}
AMOUNT_TOLERANCE = 0.01

PAYMENT_PROOF_PROMPT = """Eres un asistente de una agencia de grupos de restauración.
Te paso un correo de una agencia de viajes que nos debe el pago de una reserva, con el nombre de sus adjuntos y el
texto de los adjuntos PDF. Decide si es (o trae) el justificante de una transferencia o pago.
Responde SOLO un JSON con estas claves exactas: "es_justificante" (true/false), "importe" (número en euros o null),
"fecha" (fecha del pago en formato AAAA-MM-DD o null), "referencia" (referencia u ordenante de la transferencia o
null). Si un dato no aparece claramente, pon null -- nunca lo inventes."""


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    restagrup_payment_requested_date = fields.Datetime(string='Pago pedido a la agencia', copy=False, readonly=True)
    restagrup_payment_urgent_date = fields.Datetime(string='Pago reclamado (urgente)', copy=False, readonly=True)
    restagrup_payment_proof_state = fields.Selection(
        [('received', 'Justificante por confirmar')], string='Justificante', copy=False, readonly=True, index=True,
        help='La IA ha leído un justificante de la agencia. Una persona lo comprueba y confirma el pago.')
    restagrup_payment_proof_amount = fields.Float(string='Importe del justificante', copy=False, readonly=True)
    restagrup_payment_proof_date = fields.Char(string='Fecha del justificante', copy=False, readonly=True)
    restagrup_payment_proof_reference = fields.Char(string='Referencia del justificante', copy=False, readonly=True)
    restagrup_payment_proof_name = fields.Char(string='Archivo del justificante', copy=False, readonly=True)

    # --- pedir y reclamar el pago ---

    @api.model
    def _cron_agency_payments(self):
        """Cron diario: pide el pago al llegar el plazo y lo reclama a las 72 h. Una vez cada uno por pedido."""
        today = fields.Date.context_today(self)
        settings = self.env['restagrup.payment.settings']
        orders = self.search([
            ('state', '=', 'sale'), ('restagrup_paid', '=', False),
            ('restagrup_first_service_date', '>=', today),
            ('restagrup_first_service_date', '<=', today + timedelta(days=settings.value('payment_request_days'))),
        ])
        for order in orders:
            kind = order._restagrup_payment_kind_due(today)
            if not kind:
                continue
            try:
                with self.env.cr.savepoint():
                    order._restagrup_ask_payment(kind)
            except Exception:  # noqa: BLE001 -- un pedido roto no debe parar al resto
                _logger.exception('Petición de pago fallida para %s', order.name)

    def _restagrup_payment_kind_due(self, today):
        self.ensure_one()
        if today >= self.restagrup_payment_alert_date:
            return 'agency_payment_urgent' if not self.restagrup_payment_urgent_date else False
        if today >= self.restagrup_payment_request_date and not self.restagrup_payment_requested_date:
            return 'agency_payment_request'
        return False

    def _restagrup_agency_payment_email(self):
        return (self.partner_id.email or self.partner_id.commercial_partner_id.email or '').strip()

    def _restagrup_ask_payment(self, kind):
        self.ensure_one()
        queue = self.env['restagrup.pending.mail']
        if queue.search_count([('sale_order_id', '=', self.id), ('kind', '=', kind), ('state', '=', 'pending')]):
            return
        email_to = self._restagrup_agency_payment_email()
        if not email_to:
            _logger.warning('Pedido %s sin email de agencia: no se le pide el pago.', self.name)
            return
        subject, body = self._restagrup_payment_content(kind, self.user_id.name or self.env.company.name)
        if queue._is_automatic(kind):
            self._restagrup_post_payment_mail(kind, subject, body, email_to)
            return
        reason = _('Servicio el %s y sin pago') % self.restagrup_first_service_date.strftime('%d/%m/%Y')
        queue.create({
            'kind': kind, 'sale_order_id': self.id, 'recipient_email': email_to,
            'subject': subject, 'body': body, 'reason': reason,
        })

    def _restagrup_payment_values(self, signer):
        self.ensure_one()
        bank = self.restagrup_bank_text()
        return {
            'agencia': self.partner_id.commercial_partner_id.name or '', 'pedido': self.name,
            'grupo': self.opportunity_id.name or '',
            'fecha': self.restagrup_first_service_date.strftime('%d/%m/%Y') if self.restagrup_first_service_date else '',
            'importe': '%s €' % self.env['restagrup.pricing'].format_amount(self.amount_total),
            'cuenta': _('Cuenta para la transferencia: %s') % bank if bank else '', 'firma': signer,
        }

    def _restagrup_payment_content(self, kind, signer):
        values = self._restagrup_payment_values(signer)

        def fallback():
            text = LEGACY_PAYMENT_TEXTS[kind][1].replace('{agencia}', values['agencia'])
            return _('Pago de la reserva %s') % self.name, '\n'.join([text, '', signer])

        return self.env['restagrup.mail.template']._compose(kind, values, fallback)

    def _restagrup_post_payment_mail(self, kind, subject, body_text, email_to):
        """Sale por el hilo del pedido (la respuesta con el justificante vuelve aquí) y anota la fecha."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(self.user_id.email or self.env.user.email),
            outgoing_email_to=email_to,
        )
        self.write({PAYMENT_KINDS[kind]: fields.Datetime.now()})

    # --- el justificante ---

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for order in self:
            order._restagrup_read_payment_proof(msg_dict)
        return res

    def _restagrup_read_payment_proof(self, msg_dict):
        """La IA mira si la respuesta trae el justificante. Si lo trae, lo deja para que una persona confirme."""
        self.ensure_one()
        if self.state != 'sale' or self.restagrup_paid:
            return
        attachments = msg_dict.get('attachments') or []
        raw_body = msg_dict.get('body') or ''
        parts = [html2plaintext(raw_body).strip() if raw_body else '']
        names = [attachment[0] for attachment in attachments if attachment[0]]
        if names:
            parts.append(_('Adjuntos: %s') % ', '.join(names))
        parts.append(_attachment_text(attachments))
        text = '\n\n'.join(part for part in parts if part)
        if not text:
            return
        data, provider, _log = self.env['restagrup.llm.connector'].run(
            'payment_proof', PAYMENT_PROOF_PROMPT, text, source=self, label=self.name, review=False)
        if not data or not data.get('es_justificante'):
            return
        amount = _number(data.get('importe'))
        self.write({
            'restagrup_payment_proof_state': 'received', 'restagrup_payment_proof_amount': amount,
            'restagrup_payment_proof_date': data.get('fecha') or False,
            'restagrup_payment_proof_reference': data.get('referencia') or False,
            'restagrup_payment_proof_name': names[0] if names else False,
        })
        self._restagrup_post_proof_note(amount, provider)

    def _restagrup_post_proof_note(self, amount, provider):
        pricing = self.env['restagrup.pricing']
        note = _('Justificante de pago recibido (leído por IA, %(provider)s): %(amount)s. Compruébalo y pulsa'
                 ' «Confirmar pago».') % {
            'provider': provider, 'amount': '%s €' % pricing.format_amount(amount) if amount else _('sin importe')}
        if amount and abs(amount - self.amount_total) > AMOUNT_TOLERANCE:
            note += ' ' + _('Ojo: el importe no coincide con el total del pedido (%s €).') % pricing.format_amount(
                self.amount_total)
        self.message_post(body=note)

    def _restagrup_clear_payment_proof(self):
        self.write({name: False for name in (
            'restagrup_payment_proof_state', 'restagrup_payment_proof_amount', 'restagrup_payment_proof_date',
            'restagrup_payment_proof_reference', 'restagrup_payment_proof_name')})

    def action_mark_paid(self):
        res = super().action_mark_paid()
        self._restagrup_clear_payment_proof()
        return res

    def action_confirm_payment_proof(self):
        for order in self:
            if order.restagrup_payment_proof_state != 'received':
                raise UserError(_('No hay ningún justificante por confirmar en %s.') % order.name)
        self.action_mark_paid()

    def action_discard_payment_proof(self):
        for order in self:
            order._restagrup_clear_payment_proof()
            order.message_post(body=_('Justificante descartado: el pedido sigue sin pagar.'))


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def message_update(self, msg_dict, update_vals=None):
        """El justificante también puede llegar contestando a un correo del grupo (p. ej. la petición de datos)."""
        res = super().message_update(msg_dict, update_vals=update_vals)
        for lead in self:
            unpaid = lead._restagrup_close_orders().filtered(lambda o: not o.restagrup_paid)
            if unpaid:
                unpaid.sorted(lambda o: (o.restagrup_first_service_date or fields.Date.today(), o.id))[:1] \
                    ._restagrup_read_payment_proof(msg_dict)
        return res


class RestagrupMailTemplate(models.Model):
    _inherit = 'restagrup.mail.template'

    @api.model
    def _import_payment_texts(self):
        """Lleva a su plantilla el texto de pago que se hubiera cambiado en Ajustes y lo quita de allí."""
        params = self.env['ir.config_parameter'].sudo()
        for code, (key, default) in LEGACY_PAYMENT_TEXTS.items():
            text = (params.get_param(key) or '').strip()
            template = self._get(code)
            if text and template and text != default:
                template.body = text + '\n\n{firma}'
            if text:
                params.set_param(key, False)


class RestagrupPendingMail(models.Model):
    _inherit = 'restagrup.pending.mail'

    kind = fields.Selection(selection_add=[
        ('agency_payment_request', 'Petición de pago a la agencia'),
        ('agency_payment_urgent', 'Reclamación urgente del pago'),
    ], ondelete={'agency_payment_request': 'cascade', 'agency_payment_urgent': 'cascade'})

    def _restagrup_payment_applies(self):
        order = self.sale_order_id
        return order.state == 'sale' and not order.restagrup_paid and not order[PAYMENT_KINDS[self.kind]]

    def _restagrup_send_payment(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.sale_order_id._restagrup_post_payment_mail(self.kind, self.subject, self.body, self.recipient_email)

    def _still_applies_agency_payment_request(self):
        return self._restagrup_payment_applies()

    def _still_applies_agency_payment_urgent(self):
        return self._restagrup_payment_applies()

    def _send_agency_payment_request(self):
        self._restagrup_send_payment()

    def _send_agency_payment_urgent(self):
        self._restagrup_send_payment()
