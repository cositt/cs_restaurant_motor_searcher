# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import float_compare

NOTES_PREFIX_CHARS = 40


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    restagrup_sale_line_id = fields.Many2one(
        'sale.order.line', string='Línea de presupuesto origen',
        readonly=True, copy=False, index=True,
    )

    def _restagrup_changes(self):
        """Cambios del presupuesto respecto a lo que lleva esta línea de la hoja de servicio, como lista de
        (tipo, texto): tipo 'pax', 'date', 'hour', 'menu' o 'notes'. El texto es el que lee el restaurante."""
        self.ensure_one()
        sale_line = self.restagrup_sale_line_id
        if not sale_line:
            return []
        changes = []
        if float_compare(sale_line.product_uom_qty, self.product_qty, precision_digits=2) != 0:
            changes.append(('pax', _('Comensales %(old)g → %(new)g') % {
                'old': self.product_qty, 'new': sale_line.product_uom_qty}))
        order = sale_line.order_id
        planned = order._restagrup_local_service_datetime(sale_line)
        current = order._restagrup_to_local(self.date_planned) if self.date_planned else False
        if planned and current:
            if planned.date() != current.date():
                changes.append(('date', _('Fecha %(old)s → %(new)s') % {
                    'old': current.strftime('%d/%m/%Y'), 'new': planned.strftime('%d/%m/%Y')}))
            if planned.time() != current.time():
                changes.append(('hour', _('Hora %(old)s → %(new)s') % {
                    'old': current.strftime('%H:%M'), 'new': planned.strftime('%H:%M')}))
        if sale_line.product_id != self.product_id:
            changes.append(('menu', _('Menú: %(old)s → %(new)s') % {
                'old': self.product_id.display_name, 'new': sale_line.product_id.display_name}))
        elif sale_line.name != self.name:
            changes.append(('notes', _('Observaciones actualizadas')))
        return changes

    @api.model
    def _restagrup_fix_naive_planned_dates(self):
        """Las hojas creadas antes de pasar la hora a UTC guardaban la hora local tal cual (salía 1 h tarde).
        Solo corrige las líneas cuya llegada coincide con esa hora local: repetirlo no cambia nada."""
        lines = self.search([('restagrup_sale_line_id.service_date', '!=', False), ('date_planned', '!=', False)])
        fixed = 0
        for line in lines:
            sale_line = line.restagrup_sale_line_id
            order = sale_line.order_id
            if line.date_planned == order._restagrup_local_service_datetime(sale_line):
                planned = order._restagrup_planned_datetime(sale_line)
                if planned != line.date_planned:
                    line.date_planned = planned
                    fixed += 1
        return fixed

    def _restagrup_change_texts(self):
        """Textos de los cambios de esta línea; con varias líneas en la hoja se antepone el evento."""
        self.ensure_one()
        prefix = ''
        if len(self.order_id.order_line) > 1:
            prefix = '%s: ' % (self.name or '').splitlines()[0][:NOTES_PREFIX_CHARS]
        return [prefix + text for _kind, text in self._restagrup_changes()]
