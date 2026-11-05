# -*- coding: utf-8 -*-
"""Simulación de los correos que llegan de fuera (agencia y restaurantes) y del paso del tiempo. Los correos entran
por la misma pasarela que un buzón real (`mail.thread.message_process`), sin IMAP/SMTP, y contestan en el hilo del
correo que salió (In-Reply-To), igual que haría un cliente de correo."""
import io
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError

from .demo_guide import AGENCY_FROM, PAYMENT_KINDS, QUOTE_RESTAURANTS

AGENCY_SUBJECT = 'Comida para un grupo senior en Sevilla'
AGENCY_REFERENCE = 'Senior Andalucía CV-2611'  # la referencia del grupo: da el título de la petición
SERVICE_IN_DAYS = 5  # el grupo viene en 5 días: dentro del plazo en el que se piden los pagos (7 días)
GRATUITIES = 2
DEMO_IBAN = 'ES91 2100 0418 4502 0005 1332'  # IBAN de ejemplo de la documentación bancaria (válido, no real)
WEEKDAYS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
          'noviembre', 'diciembre')
AGENCY_BODY_HTML = """<div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">
<p>Buenos días:</p>
<p>Os escribo de Costa Viajes Ibéricos. Estamos cerrando un circuito por Andalucía para un grupo senior y
necesitamos una comida de grupo en Sevilla el día que pasen por la ciudad.</p>
<p><b>Datos del grupo:</b></p>
<ul>
<li><b>Referencia del grupo:</b> {reference}</li>
<li><b>Destino:</b> Sevilla</li>
<li><b>Personas:</b> 45 en total (todos mayores de 65 años)</li>
<li><b>Servicio:</b> comida de mediodía</li>
<li><b>Fecha:</b> todavía sin confirmar; el hotel aún no nos ha confirmado el día de llegada. Os la paso en cuanto
la tengamos.</li>
<li><b>Necesidades:</b> menú sencillo, sin picantes, y local con buen acceso para el autobús y sin escaleras.</li>
</ul>
<p>¿Nos podéis enviar dos o tres opciones con el menú y el precio por persona (IVA incluido)?</p>
<p>Muchas gracias y un saludo,</p>
<p style="color: #555;"><b>Lucía Prieto</b><br/>Departamento de Grupos<br/><b>Costa Viajes Ibéricos</b><br/>
Calle Larios 12, 29005 Málaga<br/>
Tel. 952 000 000 · www.costaviajes.demo</p>
<p style="color: #999; font-size: 11px;">Este mensaje y sus anexos son confidenciales y van dirigidos exclusivamente a
su destinatario.</p>
</div>""".replace('{reference}', AGENCY_REFERENCE)
# Lo que contesta cada restaurante: el menú que propone (la IA lo guarda en su ficha) con su precio por persona.
RESTAURANT_MENUS = {
    'Taberna del Patio Andaluz': ('Menú Patio Andaluz', [
        'Entrantes al centro: salmorejo cordobés, croquetas caseras y ensaladilla',
        'Principal a elegir: merluza en salsa verde o carrillada ibérica al vino tinto',
        'Postre: tocino de cielo', 'Bebidas: agua, vino de la casa, cerveza o refresco y café']),
    'Casa Giralda Grupos': ('Menú Giralda', [
        'Primero: crema de verduras de temporada', 'Segundo: solomillo de cerdo al whisky con patatas',
        'Postre: tarta de queso casera', 'Bebidas: agua, vino tinto de Rioja o refresco y café']),
    'Bodega San Telmo': ('Menú Senior San Telmo', [
        'Primero: sopa de picadillo o espinacas con garbanzos', 'Segundo: bacalao con tomate o pollo al ajillo suave',
        'Postre: arroz con leche', 'Bebidas: agua, vino de la casa o refresco y café',
        'Sin picantes y con opción de dieta blanda bajo petición']),
}


def _date_text(day):
    return '%s %d de %s de %d' % (WEEKDAYS[day.weekday()], day.day, MONTHS[day.month - 1], day.year)


def _pdf(title, rows):
    """PDF sencillo de una página (título y líneas de texto), legible por el lector de adjuntos de Odoo."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(60, 780, title)
    pdf.setFont('Helvetica', 11)
    for index, row in enumerate(rows):
        pdf.drawString(60, 745 - 18 * index, row)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _euros(amount):
    return ('%.2f' % amount).replace('.', ',')


class RestagrupDemo3GuideSimulate(models.AbstractModel):
    _inherit = 'restagrup.demo3.guide'

    # --- pasarela de correo ------------------------------------------------------------------------------------

    @api.model
    def _message(self, sender, to, subject, body, in_reply_to=False, html=False, attachment=None):
        msg = EmailMessage()
        msg['From'] = sender
        msg['To'] = to
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=False)
        msg['Message-Id'] = make_msgid(domain=sender.split('@')[-1].strip('>'))
        if in_reply_to:
            msg['In-Reply-To'] = in_reply_to
            msg['References'] = in_reply_to
        msg.set_content(body)
        if html:  # como un cliente de correo real: texto y HTML
            msg.add_alternative(html, subtype='html')
        if attachment:
            name, content = attachment
            msg.add_attachment(content, maintype='application', subtype='pdf', filename=name)
        return msg

    @api.model
    def _deliver(self, model, raw_message):
        # Como la pasarela real: la procesa el sistema (OdooBot), no quien pulsa el botón.
        self.env['mail.thread'].with_user(SUPERUSER_ID).message_process(model, raw_message.as_bytes(), save_original=False)

    @api.model
    def _sent_message(self, record, subject=None):
        """El último correo que salió de un registro (con ese asunto, si se da): al que se contesta."""
        messages = record.message_ids.filtered(lambda m: m.subject and m.message_id)
        if subject:
            messages = messages.filtered(lambda m: m.subject == subject)
        return messages.sorted('id', reverse=True)[:1]

    # --- petición --------------------------------------------------------------------------------------------

    @api.model
    def simulate_agency_email(self):
        """La agencia manda su petición, incompleta (sin fecha): entra por la pasarela de correo."""
        if self._lead():
            return self._lead().id
        body = ('Petición de grupo %s: Sevilla, 45 personas, comida de mediodía. Fecha todavía sin confirmar.\n\n'
                'Lucía Prieto · Costa Viajes Ibéricos · Calle Larios 12, 29005 Málaga · Tel. 952 000 000') % AGENCY_REFERENCE
        self._deliver('crm.lead', self._message(
            AGENCY_FROM, 'peticiones@restagrup.local', AGENCY_SUBJECT, body, html=AGENCY_BODY_HTML))
        return self._lead().id

    @api.model
    def simulate_agency_reply(self):
        """La agencia contesta a la petición de datos, en el mismo hilo, con una fecha a SERVICE_IN_DAYS días."""
        lead = self._require(self._lead(), _('Primero simula el correo de la agencia.'))
        request = lead.message_ids.filtered(
            lambda m: m.message_type == 'email' and (m.subject or '').startswith('Datos que nos faltan'))[:1]
        if not request:
            raise UserError(_('Primero aprueba el envío de la petición de datos (menú «Pendientes de aprobar»).'))
        if not lead._restagrup_missing_request_data():
            return lead.id
        day = fields.Date.context_today(self) + timedelta(days=SERVICE_IN_DAYS)
        body = ('Hola, gracias por escribirnos.\n\nYa tenemos la fecha: el %s, a las 14:00. No tenemos un presupuesto '
                'cerrado: lo que sea razonable para un grupo de este tipo.\n\nUn saludo,\nLucía Prieto\n') % _date_text(day)
        self._deliver('crm.lead', self._message(
            AGENCY_FROM, 'peticiones@restagrup.local', 'Re: %s' % request.subject, body, in_reply_to=request.message_id))
        return lead.id

    # --- restaurantes ----------------------------------------------------------------------------------------

    @api.model
    def request_quotes(self):
        """Atajo de «Pedir presupuesto a interesados»: el clic de quien presenta es la aprobación."""
        search = self._require(self._rg_search(), _('Primero busca restaurantes desde la petición.'))
        lines = self._require(self._quote_lines(search), _('Primero busca restaurantes desde la petición.'))
        for line in lines.filtered(lambda l: not l.quote_requested_date):
            line.action_request_quote()
        return search.id

    @api.model
    def simulate_restaurant_replies(self):
        """Los tres restaurantes contestan en el hilo de su petición, cada uno con su menú y su precio."""
        search = self._rg_search()
        lines = self._quote_lines(search) if search else False
        if not lines or not all(lines.mapped('quote_requested_date')):
            raise UserError(_('Primero pide presupuesto a los tres restaurantes.'))
        pax = search.min_capacity or 45
        for line in lines.filtered(lambda l: not l.quote_amount):
            request = self._sent_message(line)
            price = QUOTE_RESTAURANTS[line.name]
            menu_name, dishes = RESTAURANT_MENUS[line.name]
            body = (
                'Hola,\n\nGracias por contactar con nosotros. Tenemos disponibilidad para vuestro grupo de %(pax)d '
                'personas.\n\nOs proponemos nuestro %(menu)s (menú de almuerzo para grupos):\n%(dishes)s\n\nPrecio: %(price)s euros por persona (IVA '
                'incluido), es decir, %(total)s euros en total para el grupo. Bebidas y postre incluidos.\n\nUn saludo,\n'
                '%(name)s\nReservas de grupos\n' % {
                    'pax': pax, 'menu': menu_name, 'dishes': '\n'.join('- %s' % dish for dish in dishes),
                    'price': _euros(price), 'total': _euros(price * pax), 'name': line.name})
            self._deliver('restagrup.restaurant.search.line', self._message(
                '%s <%s>' % (line.name, line.email or line.partner_id.email), 'respuestas@restagrup.local',
                'Re: %s' % (request.subject or 'Petición de presupuesto'), body,
                in_reply_to=request.message_id or False))
            if not line.menu_id:  # si la IA no lo enlazó, el menú de 2026 de su ficha
                line.menu_id = self.env['restagrup.restaurant.menu'].sudo().search(
                    [('partner_id', '=', line.partner_id.id), ('season', '=', 2026)], limit=1)
        return search.id

    @api.model
    def confirm_quotes(self):
        """Una persona confirma los importes que propuso la IA (aquí, con un clic para los tres)."""
        search = self._rg_search()
        lines = self._quote_lines(search) if search else False
        if not lines or not any(lines.mapped('quote_amount')):
            raise UserError(_('Primero tienen que contestar los restaurantes.'))
        for line in lines.filtered(lambda l: l.quote_amount and l.etiqueta != 'presupuesto_recibido'):
            line.action_register_quote()
        return search.id

    # --- expediente ------------------------------------------------------------------------------------------

    @api.model
    def apply_gratuities(self):
        """Dos gratuidades (guía y chófer): no pagan, pero cuentan como comensales en los documentos."""
        order = self._require(self._rg_order(), _('Primero crea el presupuesto de venta.'))
        line = order.order_line.filtered('restaurant_id')[:1]
        if line and not line.restagrup_gratuities:
            line.write({'product_uom_qty': line.product_uom_qty - GRATUITIES, 'restagrup_gratuities': GRATUITIES})
        return order.id

    @api.model
    def simulate_restaurant_confirmation(self):
        """El restaurante contesta a la hoja de servicio confirmando la reserva: la IA lo clasifica como aceptado."""
        sheet = self._require(self._rg_sheet(), _('Primero firma el presupuesto.'))
        if sheet.state not in ('sent', 'purchase'):
            raise UserError(_('Primero envía la hoja de servicio al restaurante («Enviar hojas de servicio»).'))
        sent = self._sent_message(sheet)
        body = ('Buenos días:\n\nConfirmamos la reserva del grupo de Costa Viajes Ibéricos tal y como viene en la hoja '
                'de servicio: menú, comensales y hora. Tendremos el salón de la planta baja preparado, sin escaleras, y '
                'aparcamiento para el autobús en la puerta.\n\nUn saludo,\n%s\nReservas de grupos\n') % sheet.partner_id.name
        self._deliver('purchase.order', self._message(
            '%s <%s>' % (sheet.partner_id.name, sheet.partner_id.email), 'respuestas@restagrup.local',
            'Re: %s' % (sent.subject or sheet.name), body, in_reply_to=sent.message_id or False))
        return sheet.id

    # --- el paso del tiempo ----------------------------------------------------------------------------------

    @api.model
    def run_daily_checks(self):
        """La revisión diaria que el sistema hace solo cada mañana (pagos, cuentas, datos que faltan, facturas)."""
        env = self.env
        env['sale.order'].sudo()._cron_agency_payments()
        env['purchase.order'].sudo()._cron_restaurant_payments()
        env['restagrup.lead.event'].sudo()._cron_final_data_reminders()
        env['purchase.order'].sudo()._cron_restaurant_invoice_claims()
        return True

    @api.model
    def simulate_service_done(self):
        """Pasa el día del servicio: se adelanta la fecha del grupo a ayer y corre la revisión diaria (que ya
        prepara la primera reclamación de la factura al restaurante)."""
        order = self._require(self._rg_order(), _('Primero firma el presupuesto.'))
        yesterday = fields.Date.context_today(self) - timedelta(days=1)
        order.order_line.filtered('service_date').write({'service_date': yesterday})
        lead = self._lead()
        lead.restagrup_event_ids.sudo().write({'event_date': yesterday})
        # Es un truco de la demo, no un cambio real: la hoja se mueve igual, sin reenviar ni pedir confirmación
        for sheet in order.restaurant_po_ids.sudo().filtered('restagrup_needs_resend'):
            order._restagrup_apply_changes_to_sheet(sheet)
        self.run_daily_checks()
        return order.id

    # --- pagos y facturas ------------------------------------------------------------------------------------

    @api.model
    def _approved(self, kinds, message, order=None, sheet=None):
        pending = self._pending_for(kinds, order=order, sheet=sheet).filtered(lambda p: p.state == 'sent')
        return self._require(pending.sorted('id', reverse=True)[:1], message)

    @api.model
    def simulate_agency_payment_proof(self):
        """La agencia contesta a la petición de pago con el justificante de la transferencia en PDF."""
        order = self._require(self._rg_order(), _('Primero firma el presupuesto.'))
        pending = self._approved(PAYMENT_KINDS, _('Primero aprueba la petición de pago a la agencia.'), order=order)
        sent = self._sent_message(order, pending.subject)
        today = fields.Date.context_today(self)
        pdf = _pdf('JUSTIFICANTE DE TRANSFERENCIA', [
            'Banco Ficticio del Sur, S.A.', 'Ordenante: Costa Viajes Ibéricos, S.L.',
            'Beneficiario: %s' % order.company_id.name, 'Fecha de la operación: %s' % today.strftime('%d/%m/%Y'),
            'Importe: %s EUR' % _euros(order.amount_total), 'Concepto: Pago reserva %s' % order.name,
            'Referencia: TRF-%s-0001' % today.strftime('%Y%m%d')])
        body = 'Hola,\n\nOs adjuntamos el justificante de la transferencia de la reserva %s.\n\nUn saludo,\nLucía Prieto\n' % order.name
        self._deliver('sale.order', self._message(
            AGENCY_FROM, 'peticiones@restagrup.local', 'Re: %s' % (sent.subject or pending.subject), body,
            in_reply_to=sent.message_id or False, attachment=('Justificante transferencia %s.pdf' % order.name, pdf)))
        return order.id

    @api.model
    def simulate_restaurant_bank(self):
        """El restaurante contesta a la petición de cuenta con su IBAN."""
        sheet = self._require(self._rg_sheet(), _('Primero firma el presupuesto.'))
        pending = self._approved(['restaurant_bank_request'], _('Primero aprueba la petición de la cuenta bancaria.'),
                                 sheet=sheet)
        sent = self._sent_message(sheet, pending.subject)
        body = ('Hola,\n\nNuestro número de cuenta para la transferencia es %s (titular: %s).\n\nUn saludo,\n'
                'Administración\n') % (DEMO_IBAN, sheet.partner_id.name)
        self._deliver('purchase.order', self._message(
            '%s <%s>' % (sheet.partner_id.name, sheet.partner_id.email), 'respuestas@restagrup.local',
            'Re: %s' % (sent.subject or pending.subject), body, in_reply_to=sent.message_id or False))
        return sheet.id

    @api.model
    def simulate_restaurant_invoice(self):
        """El restaurante contesta a la reclamación con su factura en PDF (importe de la hoja y nuestro CIF)."""
        sheet = self._require(self._rg_sheet(), _('Primero firma el presupuesto.'))
        pending = self._approved(['restaurant_invoice_claim'], _('Primero aprueba la reclamación de la factura.'),
                                 sheet=sheet)
        sent = self._sent_message(sheet, pending.subject)
        company = sheet.company_id
        today = fields.Date.context_today(self)
        pdf = _pdf('FACTURA F-2026-0153', [
            'Emisor: %s · CIF B41000001' % sheet.partner_id.name,
            'Cliente: %s · CIF %s' % (company.name, company.vat or ''),
            'Fecha de factura: %s' % today.strftime('%d/%m/%Y'), 'Número de factura: F-2026-0153',
            'Concepto: Servicio de comida de grupo, reserva %s' % sheet.name,
            'Base imponible: %s EUR' % _euros(sheet.amount_untaxed), 'IVA: %s EUR' % _euros(sheet.amount_tax),
            'Total factura: %s EUR' % _euros(sheet.amount_total)])
        body = 'Hola,\n\nOs adjuntamos la factura del servicio del grupo. Disculpad el retraso.\n\nUn saludo,\nAdministración\n'
        self._deliver('purchase.order', self._message(
            '%s <%s>' % (sheet.partner_id.name, sheet.partner_id.email), 'respuestas@restagrup.local',
            'Re: %s' % (sent.subject or pending.subject), body, in_reply_to=sent.message_id or False,
            attachment=('Factura F-2026-0153.pdf', pdf)))
        return sheet.id
