# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext


class RestaurantChangeWizard(models.TransientModel):
    _name = 'restagrup.restaurant.change.wizard'
    _inherit = ['restagrup.firewall.mixin']
    _description = 'Cancelar o cambiar el restaurante elegido de un evento'

    search_id = fields.Many2one('restagrup.restaurant.search', string='Búsqueda', required=True, readonly=True)
    chosen_line_id = fields.Many2one(related='search_id.chosen_line_id', string='Restaurante actual')
    reason_id = fields.Many2one('restagrup.cancel.reason', string='Motivo')
    note = fields.Text(string='Nota')
    replacement_line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Sustituto',
        domain="[('search_id', '=', search_id), ('etiqueta', '=', 'presupuesto_recibido'), ('id', '!=', chosen_line_id)]",
        help='Un restaurante de esta búsqueda con presupuesto registrado. Vacío: solo se cancela.',
    )
    keep_client_price = fields.Boolean(
        string='Mantener el precio al cliente',
        help='Por defecto el presupuesto se ajusta al precio del nuevo restaurante. Marcado: el cliente paga lo mismo y'
             ' cambian solo el coste y el margen de Restagrup.',
    )
    notify_restaurant = fields.Boolean(string='Avisar al restaurante cancelado', default=True)
    template_id = fields.Many2one('restagrup.notice.template', string='Plantilla')
    subject = fields.Char(string='Asunto')
    body = fields.Html(string='Texto')

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.subject = self.template_id.subject
            self.body = self.template_id.body

    def _check(self):
        search, old, new = self.search_id, self.search_id.chosen_line_id, self.replacement_line_id
        if not old:
            raise UserError(_('Esta búsqueda no tiene restaurante elegido.'))
        if not self.reason_id:
            raise UserError(_('Indica el motivo de la cancelación.'))
        if new and (new == old or new.search_id != search or new.etiqueta != 'presupuesto_recibido'):
            raise UserError(_('El sustituto debe ser otro restaurante de esta búsqueda con presupuesto registrado.'))
        if self.notify_restaurant:
            if not self.subject or not html2plaintext(self.body or '').strip():
                raise UserError(_('Escribe el asunto y el texto del aviso, o desmarca "avisar al restaurante".'))
            if not (old.partner_id.email or '').strip():
                raise UserError(_('%s no tiene email: añádeselo o desmarca el aviso.') % old.name)
            if not self.env.user.email:
                raise UserError(_('Tu usuario no tiene email: añádelo antes de enviar avisos.'))

    def _restagrup_firewall_log_target(self):
        return self.search_id.lead_id

    def _fw_review_restaurant_notice(self):
        if not self.notify_restaurant:
            return False
        old, new = self.chosen_line_id, self.replacement_line_id
        return _(
            'Se cancelará %(old)s y se le escribirá a %(email)s.\nSustituto: %(new)s.\n\nAsunto: %(subject)s\n\n'
            '%(body)s') % {
            'old': old.name, 'email': (old.partner_id.email or '').strip() or '—',
            'new': new.name if new else _('ninguno (solo se cancela)'), 'subject': self.subject or '',
            'body': html2plaintext(self.body or '').strip()}

    def action_confirm(self):
        self.ensure_one()
        self._check()
        return self._restagrup_gated('notify_restaurant', '_restagrup_do_confirm')

    def _restagrup_do_confirm(self):
        self.ensure_one()
        self._check()
        search, old, new = self.search_id, self.search_id.chosen_line_id, self.replacement_line_id
        order = search.sale_order_id
        old_lines = order.order_line.filtered(lambda l: l.restagrup_search_line_id == old) if order else self.env['sale.order.line']
        sheets = order.sudo().restaurant_po_ids.filtered(
            lambda po: po.partner_id == old.partner_id and po.state != 'cancel') if order else self.env['purchase.order']
        old.write({
            'etiqueta': 'cancelado', 'cancel_reason_id': self.reason_id.id, 'cancel_note': self.note or False,
            'cancelled_date': fields.Datetime.now(),
        })
        search.chosen_line_id = False
        self._cancel_sheets(sheets, old_lines)
        if new:
            self._replace_lines(order, old_lines, new)
            new._choose_line()
        else:
            self._drop_lines(order, old_lines)
            search.sale_order_id = False  # vuelve a "presupuestos recibidos": se podrá elegir otro
        if order and order.state == 'sale':
            order._sync_restaurant_purchase_orders()
        if self.notify_restaurant:
            self._send_notice(old, sheets[:1])
        self._log(order, old, new)
        return {'type': 'ir.actions.act_window_close'}

    def _cancel_sheets(self, sheets, old_lines):
        for sheet in sheets.sudo():
            sheet_lines = sheet.order_line.filtered(lambda l: l.restagrup_sale_line_id in old_lines)
            if sheet_lines == sheet.order_line:
                sheet.button_cancel()
            elif sheet.state in ('draft', 'sent'):
                sheet_lines.unlink()
            else:
                sheet.message_post(body=_(
                    'Se canceló un servicio de este restaurante, pero la hoja tiene otras líneas y ya está confirmada:'
                    ' revísala a mano.'))

    def _replace_lines(self, order, old_lines, new):
        if not order or not old_lines:
            return
        pricing = self.env['restagrup.pricing']
        search = self.search_id
        qty, unit_cost = search._quote_figures(new.quote_amount)
        total_cost = new.quote_amount
        if self.keep_client_price:
            price = sum(l.price_unit * l.product_uom_qty * (1 - (l.discount or 0.0) / 100.0) for l in old_lines) / qty
            pct = round((price * qty / total_cost - 1) * 100, 2) if total_cost else 0.0
        else:
            price = pricing.apply_margin(unit_cost, partner=new.partner_id)
            pct = pricing.margin_percent(partner=new.partner_id)
        description = _('Servicio en %(restaurant)s — %(city)s, %(pax)s pax') % {
            'restaurant': new.name, 'city': search.city or '', 'pax': search.min_capacity or '?'}
        description += search._menu_description(new)
        label = search._event_label()
        old_lines[:1].write({
            'product_id': self.env.ref('restagrup_service_orders.product_restaurant_service').id,
            'product_uom_qty': qty,
            'name': '%s — %s' % (label, description) if label else description,
            'restaurant_id': new.partner_id.id,
            'restagrup_search_line_id': new.id,
            'restagrup_unit_cost': unit_cost,
            'restagrup_margin_pct': pct,
            'price_unit': price,
        })
        self._drop_lines(order, old_lines[1:])

    def _drop_lines(self, order, lines):
        if not order or not lines:
            return
        if order.state in ('draft', 'sent'):
            lines.unlink()
        else:  # confirmado: no se puede borrar una línea, se deja a cero y marcada
            for line in lines:
                line.write({'product_uom_qty': 0, 'name': 'CANCELADO — %s' % line.name})

    def _send_notice(self, old, sheet):
        search = self.search_id
        notice_wizard = self.env['restagrup.restaurant.notice.wizard'].create({
            'lead_id': search.lead_id.id,
            'line_ids': [(0, 0, {
                'restaurant_id': old.partner_id.id,
                'event_label': search._event_label() or search.display_name,
                'search_line_id': old.id,
                'po_id': sheet.id if sheet else False,
            })],
        })
        notice_wizard.line_ids._send_notice(self.subject, self.body)

    def _log(self, order, old, new):
        search = self.search_id
        text = _('%(old)s cancelado (%(reason)s)') % {'old': old.name, 'reason': self.reason_id.name}
        if new:
            text += _(' y sustituido por %s.') % new.name
        search.message_post_if_exists(text)
        if order and order.state == 'sale':
            order.message_post(body=_(
                'Cambio de restaurante en un presupuesto ya confirmado: %(old)s → %(new)s. La agencia no ha sido avisada'
                ' por Odoo: hazlo por tu cuenta si procede.'
            ) % {'old': old.name, 'new': new.name if new else _('(sin sustituto)')})
