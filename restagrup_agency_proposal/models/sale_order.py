# -*- coding: utf-8 -*-
from collections import defaultdict

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def restagrup_proposal_groups(self):
        """Líneas incluidas en la propuesta, agrupadas por restaurante y
        ordenadas por nombre -- usado por el report QWeb de propuesta."""
        self.ensure_one()
        grouped = defaultdict(lambda: self.env['sale.order.line'])
        for line in self.order_line:
            if line.restaurant_id and not line.display_type and line.restagrup_include_in_proposal:
                grouped[line.restaurant_id] |= line
        return sorted(grouped.items(), key=lambda item: item[0].name or '')

    restagrup_paid = fields.Boolean(string='Pagado', copy=False, tracking=True)
    restagrup_paid_date = fields.Datetime(string='Fecha de pago', copy=False)
    restagrup_observations = fields.Text(
        string='Observaciones',
        help='Salen en la confirmación de la agencia y en la del restaurante (contacto del guía, intolerancias,'
             ' detalles logísticos). Las notas internas se escriben en el chatter y no salen en ningún documento.',
    )

    def restagrup_document_services(self):
        """Servicios con restaurante del pedido, en orden de fecha, para los documentos."""
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: l.restaurant_id and not l.display_type).sorted(
            lambda l: (l.service_date or fields.Date.today(), l.service_hour or 0.0, l.id))
        return [dict(line._restagrup_service_info(), index=index) for index, line in enumerate(lines, start=1)]

    def restagrup_bank_text(self):
        """Cuenta bancaria de la empresa para el pago por transferencia (se configura en la propia compañía)."""
        self.ensure_one()
        bank = self.company_id.partner_id.bank_ids[:1]
        if not bank:
            return ''
        number = bank.acc_number or ''
        grouped = ' '.join(number[i:i + 4] for i in range(0, len(number), 4)) if ' ' not in number else number
        return ('%s: %s' % (bank.bank_id.name, grouped)) if bank.bank_id else grouped

    def action_confirmation_agency(self):
        """Confirmación a la agencia: antes de generarla, el cortafuegos comprueba que todo cuadra."""
        return self._restagrup_gated('confirm_agency', '_restagrup_do_confirmation_agency')

    def _restagrup_do_confirmation_agency(self):
        return self.env.ref('restagrup_agency_proposal.action_report_booking_confirmation').report_action(self)

    def action_mark_paid(self):
        for order in self:
            order.write({'restagrup_paid': True, 'restagrup_paid_date': fields.Datetime.now()})
            order.message_post(body=_('Marcado como pagado.'))

    def action_unmark_paid(self):
        for order in self:
            order.write({'restagrup_paid': False, 'restagrup_paid_date': False})
            order.message_post(body=_('Pago desmarcado.'))

    def action_print_voucher(self):
        """Bono de servicio: solo existe cuando el pago está recibido y marcado."""
        self.ensure_one()
        if not self.restagrup_paid:
            raise UserError(_('El bono de agencia se emite cuando el pago está recibido: marca antes el pedido como pagado.'))
        return self.env.ref('restagrup_agency_proposal.action_report_booking_voucher').report_action(self)

    restagrup_first_service_date = fields.Date(
        string='Primer servicio', compute='_compute_restagrup_service_dates', store=True)
    restagrup_last_service_date = fields.Date(
        string='Último servicio', compute='_compute_restagrup_service_dates', store=True)
    restagrup_payment_request_date = fields.Date(
        string='Pedir el pago', compute='_compute_restagrup_payment_deadlines',
        help='Fecha en la que toca pedir el pago a la agencia (plazo configurable en Ajustes → Restagrup).')
    restagrup_payment_alert_date = fields.Date(
        string='Aviso si no hay pago', compute='_compute_restagrup_payment_deadlines',
        help='Fecha en la que administración avisa si el pago no ha llegado.')
    restagrup_restaurant_payment_date = fields.Date(
        string='Pagar a restaurantes', compute='_compute_restagrup_payment_deadlines',
        help='Fecha límite para pagar a los restaurantes y enviarles el justificante.')
    restagrup_invoice_deadline = fields.Date(
        string='Facturar antes de', compute='_compute_restagrup_payment_deadlines',
        help='Las facturas se envían después del último servicio y dentro de este plazo.')
    restagrup_payment_request_text = fields.Text(
        string='Texto para pedir el pago', compute='_compute_restagrup_payment_texts')
    restagrup_payment_urgent_text = fields.Text(
        string='Texto del recordatorio urgente', compute='_compute_restagrup_payment_texts')

    @api.depends('order_line.service_date')
    def _compute_restagrup_service_dates(self):
        for order in self:
            dates = [d for d in order.order_line.mapped('service_date') if d]
            order.restagrup_first_service_date = min(dates) if dates else False
            order.restagrup_last_service_date = max(dates) if dates else False

    @api.depends('restagrup_first_service_date', 'restagrup_last_service_date')
    def _compute_restagrup_payment_deadlines(self):
        settings = self.env['restagrup.payment.settings']
        request = timedelta(days=settings.value('payment_request_days'))
        alert = timedelta(hours=settings.value('payment_alert_hours'))
        restaurant = timedelta(hours=settings.value('restaurant_payment_hours'))
        invoice = timedelta(days=settings.value('invoice_days'))
        for order in self:
            first, last = order.restagrup_first_service_date, order.restagrup_last_service_date
            order.restagrup_payment_request_date = first - request if first else False
            order.restagrup_payment_alert_date = first - alert if first else False
            order.restagrup_restaurant_payment_date = first - restaurant if first else False
            order.restagrup_invoice_deadline = last + invoice if last else False

    @api.depends('partner_id')
    def _compute_restagrup_payment_texts(self):
        settings = self.env['restagrup.payment.settings']
        for order in self:
            agency = order.partner_id.commercial_partner_id.name or ''
            order.restagrup_payment_request_text = settings.text('payment_request_text').replace('{agencia}', agency)
            order.restagrup_payment_urgent_text = settings.text('payment_urgent_text').replace('{agencia}', agency)

    def restagrup_final_pax_hours(self):
        return self.env['restagrup.payment.settings'].value('final_pax_hours')
