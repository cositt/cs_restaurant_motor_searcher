# -*- coding: utf-8 -*-
from collections import defaultdict

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    restaurant_po_ids = fields.One2many(
        'purchase.order', 'restagrup_sale_order_id', string='Hojas de servicio',
    )
    restaurant_po_count = fields.Integer(compute='_compute_restaurant_po_count')
    restaurant_changes_pending = fields.Boolean(compute='_compute_restaurant_changes_pending')

    def _compute_restaurant_po_count(self):
        for order in self:
            order.restaurant_po_count = len(order.restaurant_po_ids)

    @api.depends('restaurant_po_ids.restagrup_needs_resend')
    def _compute_restaurant_changes_pending(self):
        for order in self:
            order.restaurant_changes_pending = bool(
                order.restaurant_po_ids.filtered('restagrup_needs_resend')
            )

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            order._sync_restaurant_purchase_orders()
        return res

    def _sync_restaurant_purchase_orders(self):
        """Genera una hoja de servicio (purchase.order) por cada restaurante nuevo
        en las líneas de este presupuesto, y añade a las hojas ya existentes las
        líneas nuevas que aparezcan para un restaurante que ya tenía una."""
        self.ensure_one()
        lines_by_restaurant = defaultdict(lambda: self.env['sale.order.line'])
        for line in self.order_line:
            if line.restaurant_id and not line.display_type:
                lines_by_restaurant[line.restaurant_id] |= line

        po_by_restaurant = {po.partner_id: po for po in self.restaurant_po_ids}
        for restaurant, lines in lines_by_restaurant.items():
            po = po_by_restaurant.get(restaurant)
            if not po:
                self.env['purchase.order'].create({
                    'partner_id': restaurant.id,
                    'origin': self.name,
                    'restagrup_sale_order_id': self.id,
                    'order_line': [
                        (0, 0, self._prepare_restaurant_po_line_vals(line)) for line in lines
                    ],
                })
                continue
            tracked_ids = set(po.order_line.restagrup_sale_line_id.ids)
            new_lines = lines.filtered(lambda l: l.id not in tracked_ids)
            if new_lines:
                po.write({
                    'order_line': [
                        (0, 0, self._prepare_restaurant_po_line_vals(line)) for line in new_lines
                    ],
                })

    def _prepare_restaurant_po_line_vals(self, sale_line):
        planned = sale_line.service_date and fields.Datetime.to_datetime(sale_line.service_date)
        return {
            'product_id': sale_line.product_id.id,
            'name': sale_line.name,
            'product_qty': sale_line.product_uom_qty,
            'product_uom_id': sale_line.product_uom_id.id,
            'price_unit': sale_line.price_unit,
            'date_planned': planned or fields.Datetime.now(),
            'restagrup_sale_line_id': sale_line.id,
        }

    def action_send_restaurant_orders(self):
        template = self.env.ref('purchase.email_template_edi_purchase', raise_if_not_found=False)
        for order in self:
            order._sync_restaurant_purchase_orders()
            draft_pos = order.restaurant_po_ids.filtered(lambda po: po.state == 'draft')
            for po in draft_pos:
                if template:
                    template.send_mail(po.id, force_send=True)
                po.write({'state': 'sent'})

    def action_resend_restaurant_orders(self):
        """Botón 'reenviar cambios': solo toca las hojas de servicio marcadas
        como restagrup_needs_resend, actualiza las líneas que cambiaron
        (comensales/notas), deja constancia en el chatter y reenvía el email --
        únicamente a los restaurantes afectados, no a todos."""
        template = self.env.ref('purchase.email_template_edi_purchase', raise_if_not_found=False)
        for order in self:
            order._sync_restaurant_purchase_orders()
            for po in order.restaurant_po_ids.filtered('restagrup_needs_resend'):
                changed_lines = po._restagrup_changed_lines()
                change_log = []
                for line in changed_lines:
                    sale_line = line.restagrup_sale_line_id
                    if float_compare(sale_line.product_uom_qty, line.product_qty, precision_digits=2) != 0:
                        change_log.append(
                            _('%(line)s: %(old)s → %(new)s comensales')
                            % {'line': line.name, 'old': line.product_qty, 'new': sale_line.product_uom_qty}
                        )
                    if sale_line.name != line.name:
                        change_log.append(_('%(line)s: notas actualizadas') % {'line': line.name})
                    line.write({
                        'product_qty': sale_line.product_uom_qty,
                        'name': sale_line.name,
                    })
                if change_log:
                    po.message_post(
                        body=Markup('<p>%s</p><ul>%s</ul>') % (
                            _('Cambios detectados en el presupuesto, reenviado al restaurante:'),
                            Markup('').join(Markup('<li>%s</li>') % entry for entry in change_log),
                        )
                    )
                if template:
                    template.send_mail(po.id, force_send=True)

    def action_view_restaurant_pos(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('purchase.purchase_rfq')
        action['domain'] = [('id', 'in', self.restaurant_po_ids.ids)]
        action['context'] = {}
        return action
