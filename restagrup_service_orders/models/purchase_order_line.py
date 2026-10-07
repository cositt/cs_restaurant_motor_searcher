# -*- coding: utf-8 -*-
from odoo import _, fields, models
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
        planned = sale_line.order_id._restagrup_planned_datetime(sale_line)
        current = self.date_planned
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

    def _restagrup_change_texts(self):
        """Textos de los cambios de esta línea; con varias líneas en la hoja se antepone el evento."""
        self.ensure_one()
        prefix = ''
        if len(self.order_id.order_line) > 1:
            prefix = '%s: ' % (self.name or '').splitlines()[0][:NOTES_PREFIX_CHARS]
        return [prefix + text for _kind, text in self._restagrup_changes()]
