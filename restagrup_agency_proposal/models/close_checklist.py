# -*- coding: utf-8 -*-
"""Cierre del expediente: los cuatro pasos que tienen que estar hechos antes de pasarlo a «Cerrado»."""
from odoo import _, api, fields, models

ORDER_PATHS = ('order_ids', 'restagrup_restaurant_search_ids.sale_order_id')
ORDER_FIELDS = ('state', 'restagrup_paid', 'restagrup_invoice_sent',
                'restaurant_po_ids.state', 'restaurant_po_ids.restagrup_restaurant_paid',
                'restaurant_po_ids.restagrup_invoice_received')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    restagrup_invoice_sent = fields.Boolean(string='Factura enviada a la agencia', copy=False, tracking=True)
    restagrup_invoice_sent_date = fields.Datetime(string='Fecha de envío de la factura', copy=False)

    def action_mark_invoice_sent(self):
        for order in self:
            order.write({'restagrup_invoice_sent': True, 'restagrup_invoice_sent_date': fields.Datetime.now()})
            order.message_post(body=_('Factura enviada a la agencia.'))

    def action_unmark_invoice_sent(self):
        for order in self:
            order.write({'restagrup_invoice_sent': False, 'restagrup_invoice_sent_date': False})
            order.message_post(body=_('Factura a la agencia desmarcada.'))


class PurchaseOrder(models.Model):
    """La hoja de servicio de cada restaurante: aquí se marca su transferencia y su factura."""
    _inherit = 'purchase.order'

    restagrup_restaurant_paid = fields.Boolean(string='Transferencia hecha', copy=False, tracking=True)
    restagrup_restaurant_paid_date = fields.Datetime(string='Fecha de la transferencia', copy=False)
    restagrup_invoice_received = fields.Boolean(
        string='Factura recibida y revisada', copy=False, tracking=True,
        help='La factura del restaurante ha llegado, los datos son correctos y está guardada.')
    restagrup_invoice_received_date = fields.Datetime(string='Fecha de la factura recibida', copy=False)

    def _restagrup_mark(self, field, value, note):
        for sheet in self:
            sheet.write({field: value, '%s_date' % field: fields.Datetime.now() if value else False})
            sheet.message_post(body=note)

    def action_mark_restaurant_paid(self):
        self._restagrup_mark('restagrup_restaurant_paid', True, _('Transferencia al restaurante hecha.'))

    def action_unmark_restaurant_paid(self):
        self._restagrup_mark('restagrup_restaurant_paid', False, _('Transferencia al restaurante desmarcada.'))

    def action_mark_invoice_received(self):
        self._restagrup_mark('restagrup_invoice_received', True, _('Factura del restaurante recibida y revisada.'))

    def action_unmark_invoice_received(self):
        self._restagrup_mark('restagrup_invoice_received', False, _('Factura del restaurante desmarcada.'))


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_close_agency_paid = fields.Boolean(string='Pago de la agencia', compute='_compute_restagrup_close')
    restagrup_close_restaurant_paid = fields.Boolean(
        string='Transferencia al restaurante', compute='_compute_restagrup_close')
    restagrup_close_invoice_sent = fields.Boolean(string='Factura a la agencia', compute='_compute_restagrup_close')
    restagrup_close_restaurant_invoice = fields.Boolean(
        string='Factura del restaurante', compute='_compute_restagrup_close')
    restagrup_close_ready = fields.Boolean(string='Listo para cerrar', compute='_compute_restagrup_close')
    restagrup_close_pending = fields.Char(
        string='Pendiente para cerrar', compute='_compute_restagrup_close',
        help='Lo que falta antes de pasar el expediente a «Cerrado».')

    def _restagrup_close_orders(self):
        return self._restagrup_firewall_orders().filtered(lambda o: o.state in ('sale', 'done'))

    @staticmethod
    def _restagrup_close_sheets(orders):
        return orders.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')

    @api.depends(*['%s.%s' % (path, name) for path in ORDER_PATHS for name in ORDER_FIELDS])
    def _compute_restagrup_close(self):
        for lead in self:
            orders = lead._restagrup_close_orders()
            sheets = self._restagrup_close_sheets(orders)
            steps = {
                'restagrup_close_agency_paid': bool(orders) and all(orders.mapped('restagrup_paid')),
                'restagrup_close_restaurant_paid': bool(sheets) and all(sheets.mapped('restagrup_restaurant_paid')),
                'restagrup_close_invoice_sent': bool(orders) and all(orders.mapped('restagrup_invoice_sent')),
                'restagrup_close_restaurant_invoice': bool(sheets) and all(sheets.mapped('restagrup_invoice_received')),
            }
            lead.update(steps)
            lead.restagrup_close_ready = all(steps.values())
            lead.restagrup_close_pending = ', '.join(
                lead._fields[name].string for name, done in steps.items() if not done)

    # --- cortafuegos «Cerrar expediente» ---

    def _restagrup_close_missing_on(self, records, field):
        return ', '.join(records.filtered(lambda r: not r[field]).mapped('partner_id.name'))

    def _fw_restaurant_paid(self):
        sheets = self._restagrup_close_sheets(self._restagrup_close_orders())
        if not sheets:
            return _('No hay hoja de servicio de ningún restaurante.')
        missing = self._restagrup_close_missing_on(sheets, 'restagrup_restaurant_paid')
        return _('Falta la transferencia a: %s.') % missing if missing else False

    def _fw_agency_invoice_sent(self):
        orders = self._restagrup_close_orders()
        if not orders:
            return _('No hay ningún presupuesto de venta confirmado en este grupo.')
        pending = orders.filtered(lambda o: not o.restagrup_invoice_sent)
        return _('Falta enviar la factura a la agencia: %s.') % ', '.join(pending.mapped('name')) if pending else False

    def _fw_restaurant_invoice(self):
        sheets = self._restagrup_close_sheets(self._restagrup_close_orders())
        if not sheets:
            return _('No hay hoja de servicio de ningún restaurante.')
        missing = self._restagrup_close_missing_on(sheets, 'restagrup_invoice_received')
        return _('Falta recibir y revisar la factura de: %s.') % missing if missing else False
