# -*- coding: utf-8 -*-
"""F6: la factura de cada restaurante. Se reclama a los 1, 7, 15 y 30 días del servicio (la cuarta la revisa siempre
una persona) y, cuando llega, la IA la lee y la comprueba; darla por buena lo hace una persona."""
import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.restagrup_restaurants.models.restaurant_menu_ai import _attachment_text, _number

_logger = logging.getLogger(__name__)

# Días tras el servicio en que sale cada reclamación (1.ª a 4.ª).
CLAIM_DAYS = (1, 7, 15, 30)
LAST_CLAIM = len(CLAIM_DAYS)
MAX_CLAIM_AGE_DAYS = 60  # servicios más antiguos no se reclaman (p. ej. los anteriores a la puesta en marcha)
AMOUNT_TOLERANCE = 0.01

INVOICE_PROMPT = """Eres un asistente de una agencia de grupos de restauración.
Te paso un correo de un restaurante con el nombre de sus adjuntos y el texto de los adjuntos PDF. Decide si trae la
factura del servicio que le contratamos.
Responde SOLO un JSON con estas claves exactas: "es_factura" (true/false), "numero" (número de factura o null),
"fecha" (fecha de la factura en formato AAAA-MM-DD o null), "importe_total" (total de la factura en euros, con
impuestos, o null), "nif_receptor" (NIF/CIF del cliente al que va la factura o null).
Si un dato no aparece claramente, pon null -- nunca lo inventes."""


def _tax_id(value):
    """NIF/CIF comparable: sin guiones ni espacios y sin el prefijo de país."""
    compact = re.sub(r'[^A-Z0-9]', '', (value or '').upper())
    return compact[2:] if re.match(r'^[A-Z]{2}', compact) and len(compact) > 9 else compact


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    restagrup_service_end_date = fields.Date(
        string='Último servicio', compute='_compute_restagrup_service_end_date', store=True)
    restagrup_invoice_claim_level = fields.Integer(
        string='Reclamaciones de factura', copy=False, readonly=True, help='Cuántas reclamaciones han salido (de 4).')
    restagrup_invoice_claim_date = fields.Datetime(string='Última reclamación', copy=False, readonly=True)
    restagrup_invoice_proof_state = fields.Selection(
        [('received', 'Factura por revisar')], string='Factura del restaurante', copy=False, readonly=True,
        index=True, help='La IA ha leído una factura del restaurante. Una persona la revisa y la da por buena.')
    restagrup_invoice_number = fields.Char(string='Número de factura', copy=False, readonly=True)
    restagrup_invoice_date = fields.Char(string='Fecha de la factura (IA)', copy=False, readonly=True)
    restagrup_invoice_date_display = fields.Char(
        string='Fecha de la factura', compute='_compute_restagrup_invoice_date_display',
        help='La fecha que leyó la IA, en dd/mm/aaaa (si no era una fecha, tal cual).')
    restagrup_invoice_amount = fields.Float(string='Importe de la factura', copy=False, readonly=True)
    restagrup_invoice_file_name = fields.Char(string='Archivo de la factura', copy=False, readonly=True)
    restagrup_invoice_issues = fields.Char(string='Revisar en la factura', copy=False, readonly=True)

    @api.depends('order_line.restagrup_sale_line_id.service_date')
    def _compute_restagrup_service_end_date(self):
        for sheet in self:
            dates = [d for d in sheet.order_line.mapped('restagrup_sale_line_id.service_date') if d]
            sheet.restagrup_service_end_date = max(dates) if dates else False

    @api.depends('restagrup_invoice_date')
    def _compute_restagrup_invoice_date_display(self):
        for sheet in self:
            raw = sheet.restagrup_invoice_date
            try:
                sheet.restagrup_invoice_date_display = fields.Date.to_date(raw).strftime('%d/%m/%Y') if raw else False
            except ValueError:
                sheet.restagrup_invoice_date_display = raw

    # --- reclamar ---

    @api.model
    def _cron_restaurant_invoice_claims(self):
        """Cron diario: la siguiente reclamación a quien no ha mandado la factura, una cada vez y con su espera."""
        today = fields.Date.context_today(self)
        sheets = self.search([
            ('state', '!=', 'cancel'), ('restagrup_sale_order_id', '!=', False),
            ('restagrup_invoice_received', '=', False), ('restagrup_invoice_proof_state', '=', False),
            ('restagrup_invoice_claim_level', '<', LAST_CLAIM),
            ('restagrup_service_end_date', '<', today),
            ('restagrup_service_end_date', '>=', today - timedelta(days=MAX_CLAIM_AGE_DAYS)),
        ])
        for sheet in sheets.filtered(lambda s: s._restagrup_claim_is_due(today)):
            try:
                with self.env.cr.savepoint():
                    sheet._restagrup_claim_invoice(sheet.restagrup_invoice_claim_level + 1)
            except Exception:  # noqa: BLE001 -- una hoja rota no debe parar al resto
                _logger.exception('Reclamación de factura fallida para %s', sheet.name)

    def _restagrup_claim_is_due(self, today):
        """La siguiente toca si han pasado sus días desde el servicio y, desde la anterior, la diferencia entre
        ambas: un servicio atrasado empieza por la primera y no recibe todas de golpe."""
        self.ensure_one()
        level = self.restagrup_invoice_claim_level
        if (today - self.restagrup_service_end_date).days < CLAIM_DAYS[level]:
            return False
        if level and self.restagrup_invoice_claim_date:
            waited = (fields.Datetime.now() - self.restagrup_invoice_claim_date).days
            return waited >= CLAIM_DAYS[level] - CLAIM_DAYS[level - 1]
        return True

    def _restagrup_booking_summary(self):
        self.ensure_one()
        sale_lines = self.order_line.mapped('restagrup_sale_line_id')
        values = self._restagrup_mail_values('')
        # Comensales: la línea más grande (el menú); sumar contaría también «Servicio de restaurante» (1).
        pax = int(max(sale_lines.mapped('product_uom_qty') or [0]))
        when = ' '.join(filter(None, [values['fecha'], values['hora']]))
        return '\n'.join(filter(None, [
            _('Grupo: %s') % values['grupo'], _('Servicio: %s') % when if when else '', _('%s pax') % pax,
            _('Importe: %s € (IVA incluido)') % self.env['restagrup.pricing'].format_amount(self.amount_total),
            _('Referencia: %s') % self.name,
        ]))

    def _restagrup_invoice_claim_content(self, level):
        values = dict(self._restagrup_mail_values(self._restagrup_signer()),
                      datos_reserva=self._restagrup_booking_summary())

        def fallback():
            return (_('Solicitud de factura del servicio %s') % values['grupo'], '\n'.join([
                _('Buenos días,'), '', _('Quedamos a la espera de la factura del servicio.'), '',
                _('Datos de la reserva:'), values['datos_reserva'], '',
                _('Datos fiscales de nuestra empresa:'), values['datos_fiscales'], '', values['firma']]))

        return self.env['restagrup.mail.template']._compose('restaurant_invoice_claim_%s' % level, values, fallback)

    def _restagrup_claim_invoice(self, level):
        self.ensure_one()
        queue = self.env['restagrup.pending.mail']
        if queue.search_count([('purchase_order_id', '=', self.id), ('kind', '=', 'restaurant_invoice_claim'),
                               ('state', '=', 'pending')]):
            return
        email_to = (self.partner_id.email or '').strip()
        if not email_to:
            _logger.warning('Hoja %s sin email del restaurante: no se le reclama la factura.', self.name)
            return
        subject, body = self._restagrup_invoice_claim_content(level)
        # La cuarta (tono legal) nunca sale sola, ni con el envío global en automático.
        if level < LAST_CLAIM and queue._is_automatic('restaurant_invoice_claim_%s' % level):
            self._restagrup_post_invoice_claim(level, subject, body, email_to)
            return
        queue.create({
            'kind': 'restaurant_invoice_claim', 'invoice_claim_level': level, 'purchase_order_id': self.id,
            'recipient_email': email_to, 'subject': subject, 'body': body,
            'reason': _('Reclamación %(level)s de %(total)s: servicio del %(date)s sin factura') % {
                'level': level, 'total': LAST_CLAIM, 'date': self.restagrup_service_end_date.strftime('%d/%m/%Y')},
        })

    def _restagrup_post_invoice_claim(self, level, subject, body_text, email_to):
        """Sale por el hilo de la hoja: la factura que conteste vuelve aquí."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(
                self.restagrup_sale_order_id.user_id.email or self.env.user.email),
            email_add_signature=False,  # el texto ya lleva {firma}
            outgoing_email_to=email_to,
        )
        self.write({'restagrup_invoice_claim_level': level, 'restagrup_invoice_claim_date': fields.Datetime.now()})

    # --- la factura ---

    def _restagrup_classify_response(self, msg_dict):
        """La respuesta con la factura no es la respuesta a la hoja: no se clasifica."""
        if self._restagrup_read_invoice(msg_dict):
            return False
        return super()._restagrup_classify_response(msg_dict)

    def _restagrup_read_invoice(self, msg_dict):
        """True si la respuesta traía la factura."""
        self.ensure_one()
        attachments = msg_dict.get('attachments') or []
        if (not attachments or self.state == 'cancel' or not self.restagrup_sale_order_id
                or self.restagrup_invoice_received):
            return False
        raw_body = msg_dict.get('body') or ''
        names = [attachment[0] for attachment in attachments if attachment[0]]
        text = '\n\n'.join(filter(None, [
            html2plaintext(raw_body).strip() if raw_body else '', _('Adjuntos: %s') % ', '.join(names),
            _attachment_text(attachments)]))
        data, provider, _log = self.env['restagrup.llm.connector'].run(
            'restaurant_invoice', INVOICE_PROMPT, text, source=self, label=self.name, review=False)
        if not data or not data.get('es_factura'):
            return False
        amount = _number(data.get('importe_total'))
        issues = self._restagrup_invoice_issues(data, amount)
        self.write({
            'restagrup_invoice_proof_state': 'received', 'restagrup_invoice_number': data.get('numero') or False,
            'restagrup_invoice_date': data.get('fecha') or False, 'restagrup_invoice_amount': amount,
            'restagrup_invoice_file_name': names[0] if names else False, 'restagrup_invoice_issues': issues or False,
        })
        note = _('Factura del restaurante recibida (leída por IA, %(provider)s): nº %(number)s, %(amount)s €.') % {
            'provider': provider, 'number': data.get('numero') or '?',
            'amount': self.env['restagrup.pricing'].format_amount(amount)}
        note += ' ' + (_('Revisar: %s.') % issues if issues else _('Cuadra con la hoja: compruébala y dala por buena.'))
        self.message_post(body=note)
        return True

    def _restagrup_invoice_issues(self, data, amount):
        issues = []
        if not data.get('numero'):
            issues.append(_('falta el número de factura'))
        if not amount or abs(amount - self.amount_total) > AMOUNT_TOLERANCE:
            pricing = self.env['restagrup.pricing']
            issues.append(_('el importe (%(invoice)s €) no coincide con la hoja (%(sheet)s €)') % {
                'invoice': pricing.format_amount(amount), 'sheet': pricing.format_amount(self.amount_total)})
        ours = _tax_id(self.company_id.vat)
        theirs = _tax_id(data.get('nif_receptor'))
        if not theirs:
            issues.append(_('no se ve nuestro CIF'))
        elif ours and theirs != ours:
            issues.append(_('el CIF del cliente (%(theirs)s) no es el nuestro (%(ours)s)') % {
                'theirs': data.get('nif_receptor'), 'ours': self.company_id.vat})
        return '; '.join(issues)

    def action_confirm_restaurant_invoice(self):
        for sheet in self:
            if sheet.restagrup_invoice_proof_state != 'received':
                raise UserError(_('No hay ninguna factura por revisar en %s.') % sheet.name)
        self.write({'restagrup_invoice_proof_state': False})
        self.action_mark_invoice_received()

    def action_discard_restaurant_invoice(self):
        for sheet in self:
            sheet.write({name: False for name in (
                'restagrup_invoice_proof_state', 'restagrup_invoice_number', 'restagrup_invoice_date',
                'restagrup_invoice_amount', 'restagrup_invoice_file_name', 'restagrup_invoice_issues')})
            sheet.message_post(body=_('Factura descartada: se le seguirá reclamando.'))


class RestagrupPendingMail(models.Model):
    _inherit = 'restagrup.pending.mail'

    kind = fields.Selection(selection_add=[
        ('restaurant_invoice_claim', 'Reclamación de factura al restaurante'),
    ], ondelete={'restaurant_invoice_claim': 'cascade'})
    invoice_claim_level = fields.Integer(string='Reclamación nº', readonly=True)

    def _still_applies_restaurant_invoice_claim(self):
        sheet = self.purchase_order_id
        return bool(sheet.state != 'cancel' and not sheet.restagrup_invoice_received
                    and not sheet.restagrup_invoice_proof_state
                    and sheet.restagrup_invoice_claim_level < self.invoice_claim_level)

    def _send_restaurant_invoice_claim(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.purchase_order_id._restagrup_post_invoice_claim(
            self.invoice_claim_level, self.subject, self.body, self.recipient_email)
