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
    restagrup_confirmed_count = fields.Integer(
        string='Restaurantes confirmados', compute='_compute_restagrup_confirmation',
        help='Hojas de servicio (no canceladas) cuyo restaurante ya aceptó.',
    )
    restagrup_pending_count = fields.Integer(
        string='Restaurantes sin confirmar', compute='_compute_restagrup_confirmation',
        help='Hojas de servicio (no canceladas) que aún no han sido aceptadas.',
    )
    restagrup_confirmation_summary = fields.Char(
        string='Confirmaciones', compute='_compute_restagrup_confirmation',
        help='"confirmados/total", vacío si el pedido no tiene hojas de servicio.',
    )

    def _compute_restaurant_po_count(self):
        for order in self:
            order.restaurant_po_count = len(order.restaurant_po_ids)

    @api.depends('restaurant_po_ids.restagrup_needs_resend')
    def _compute_restaurant_changes_pending(self):
        for order in self:
            order.restaurant_changes_pending = bool(
                order.restaurant_po_ids.filtered('restagrup_needs_resend')
            )

    @api.depends('restaurant_po_ids.state', 'restaurant_po_ids.restagrup_response_state')
    def _compute_restagrup_confirmation(self):
        for order in self:
            active_pos = order.restaurant_po_ids.filtered(lambda po: po.state != 'cancel')
            confirmed = len(active_pos.filtered(lambda po: po.restagrup_response_state == 'accepted'))
            order.restagrup_confirmed_count = confirmed
            order.restagrup_pending_count = len(active_pos) - confirmed
            order.restagrup_confirmation_summary = (
                '%s/%s' % (confirmed, len(active_pos)) if active_pos else False
            )

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            order._sync_restaurant_purchase_orders()
            signed = _(' (firmado por %s)') % order.signed_by if order.signed_by else ''
            order._restagrup_log_on_searches(_('Presupuesto de venta %(name)s confirmado%(signed)s.') % {
                'name': order.name, 'signed': signed,
            })
        return res

    def _restagrup_log_on_searches(self, body):
        """Refleja un suceso del presupuesto en el chatter de la búsqueda de origen."""
        searches = self.env['restagrup.restaurant.search'].search([('sale_order_id', 'in', self.ids)])
        searches.message_post_if_exists(body)

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

    def _restagrup_restaurant_cost(self, sale_line):
        """Precio que cobra el restaurante (lo que lleva su hoja de servicio): nunca el precio al
        cliente, para no enseñarle el margen de Restagrup. Menú -> su coste; petición sin menús ->
        el importe del presupuesto que dio el restaurante; línea manual -> el precio de la línea."""
        product = sale_line.product_id
        if product.restaurant_id and product.standard_price:
            return product.standard_price
        quote = sale_line.restagrup_search_line_id.quote_amount
        return quote or sale_line.price_unit

    def _prepare_restaurant_po_line_vals(self, sale_line):
        planned = sale_line.service_date and fields.Datetime.to_datetime(sale_line.service_date)
        return {
            'product_id': sale_line.product_id.id,
            'name': sale_line.name,
            'product_qty': sale_line.product_uom_qty,
            'product_uom_id': sale_line.product_uom_id.id,
            'price_unit': self._restagrup_restaurant_cost(sale_line),
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
                order._restagrup_log_on_searches(
                    _('Hoja de servicio enviada a %s.') % po.partner_id.name
                )

    def action_resend_restaurant_orders(self):
        """Botón 'reenviar cambios': solo toca las hojas de servicio marcadas
        como restagrup_needs_resend, actualiza las líneas que cambiaron
        (comensales/notas), deja constancia en el chatter y reenvía el email --
        únicamente a los restaurantes afectados, no a todos."""
        template = self.env.ref('purchase.email_template_edi_purchase', raise_if_not_found=False)
        for order in self:
            order._sync_restaurant_purchase_orders()
            resent_any = False
            for po in order.restaurant_po_ids.filtered('restagrup_needs_resend'):
                resent_any = True
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
                order._restagrup_log_on_searches(_('Cambios reenviados a %(restaurant)s: %(changes)s') % {
                    'restaurant': po.partner_id.name,
                    'changes': '; '.join(change_log) or _('sin cambios de cantidad'),
                })
            if resent_any:
                order._restagrup_send_updated_proforma()

    def _restagrup_send_updated_proforma(self):
        """Tras reenviar cambios a los restaurantes, la agencia recibe también el
        presupuesto actualizado desde el mismo botón. Sin email de agencia no se
        rompe el reenvío a restaurantes: se deja una nota para que alguien la avise."""
        self.ensure_one()
        template = self.env.ref('sale.email_template_edi_sale', raise_if_not_found=False)
        if not self.partner_id.email or not template:
            note = _(
                'Los cambios se reenviaron a los restaurantes, pero no se pudo avisar a la'
                ' agencia (%(agency)s): no tiene email. Avísala a mano.'
            ) % {'agency': self.partner_id.name}
            self.message_post(body=note)
            self._restagrup_log_on_searches(note)
            return
        template.send_mail(self.id, force_send=True)
        note = _(
            'Presupuesto actualizado enviado a la agencia (%(email)s).'
        ) % {'email': self.partner_id.email}
        self.message_post(body=note)
        self._restagrup_log_on_searches(note)

    def action_view_restaurant_pos(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('purchase.purchase_rfq')
        action['domain'] = [('id', 'in', self.restaurant_po_ids.ids)]
        action['context'] = {}
        return action
