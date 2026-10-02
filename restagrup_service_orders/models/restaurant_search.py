# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RestaurantSearch(models.Model):
    _inherit = 'restagrup.restaurant.search'

    sale_order_id = fields.Many2one(
        'sale.order', string='Presupuesto de venta', copy=False, readonly=True,
        help='Presupuesto de venta generado a partir del restaurante elegido y su'
             ' presupuesto registrado.',
    )
    pipeline_stage = fields.Selection(
        selection_add=[('sale_created', 'Presupuesto de venta creado')],
        ondelete={'sale_created': 'set default'},
    )

    @api.depends('sale_order_id')
    def _compute_pipeline_stage(self):
        super()._compute_pipeline_stage()
        for search in self:
            if search.sale_order_id:
                search.pipeline_stage = 'sale_created'

    def action_create_sale_order(self):
        self.ensure_one()
        if self.sale_order_id:
            return self._action_view_sale_order()

        line = self.chosen_line_id
        if not line:
            raise UserError(_('Elige primero un restaurante con presupuesto recibido.'))
        if line.etiqueta != 'presupuesto_recibido':
            raise UserError(_('El restaurante elegido todavía no tiene presupuesto recibido.'))
        if not line.partner_id:
            raise UserError(_(
                'El restaurante elegido no está guardado como contacto -- añádelo'
                ' como contacto antes de crear el presupuesto de venta.'
            ))
        if not self.lead_id._restagrup_ensure_billing_partner():
            raise UserError(_(
                'El grupo/cliente "%s" no tiene un contacto de facturación asignado'
                ' -- asígnalo antes de crear el presupuesto de venta.'
            ) % self.lead_id.name)

        menus = self.env['product.template'].search([
            ('restaurant_id', '=', line.partner_id.id), ('sale_ok', '=', True),
        ])
        if menus:
            return self._action_open_menu_wizard(menus)
        return self._create_sale_order_from_quote(line)

    def _action_open_menu_wizard(self, menus):
        self.ensure_one()
        wizard = self.env['restagrup.menu.selection.wizard'].create({
            'search_id': self.id,
            'line_ids': [(0, 0, {
                'product_tmpl_id': menu.id, 'quantity': self.min_capacity or 1,
            }) for menu in menus],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Elegir menús'),
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _create_sale_order_from_menus(self, selection):
        """selection: lista de (product.product, cantidad). Una línea por menú, al
        precio de venta del propio producto (sin margen: el menú ya lleva su precio)."""
        self.ensure_one()
        line = self.chosen_line_id
        event_label = self._event_label()
        commands = [(0, 0, dict(
            self._event_line_vals(),
            product_id=product.id,
            product_uom_qty=qty,
            restaurant_id=line.partner_id.id,
            restagrup_search_line_id=line.id,
            **({'name': '%s — %s' % (event_label, product.display_name)} if event_label else {}),
        )) for product, qty in selection]
        order, created = self._add_lines_to_group_order(commands)
        self._link_sale_order(order, line, created)
        return order

    def _create_sale_order_from_quote(self, line):
        self.ensure_one()
        product = self.env.ref('restagrup_service_orders.product_restaurant_service')
        description = _('Servicio en %(restaurant)s — %(city)s, %(pax)s pax') % {
            'restaurant': line.name,
            'city': self.city or '',
            'pax': self.min_capacity or '?',
        }
        event_label = self._event_label()
        order, created = self._add_lines_to_group_order([(0, 0, dict(
            self._event_line_vals(),
            product_id=product.id,
            name='%s — %s' % (event_label, description) if event_label else description,
            product_uom_qty=1,
            price_unit=self._apply_default_margin(line.quote_amount),
            restaurant_id=line.partner_id.id,
            restagrup_search_line_id=line.id,
        ))])
        self._link_sale_order(order, line, created)
        return self._action_view_sale_order()

    def action_open_change_wizard(self):
        self.ensure_one()
        if not self.chosen_line_id:
            raise UserError(_('Elige primero un restaurante.'))
        wizard = self.env['restagrup.restaurant.change.wizard'].create({'search_id': self.id})
        return {
            'type': 'ir.actions.act_window', 'name': _('Cancelar o cambiar restaurante'),
            'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
        }

    def _group_orders(self):
        """Presupuestos del grupo: los enlazados al lead y los de sus búsquedas (los creados antes de
        enlazarlos al lead)."""
        lead = self.lead_id
        return lead.order_ids | lead.restagrup_restaurant_search_ids.sale_order_id

    def _open_group_order(self):
        """Presupuesto del grupo todavía sin firmar (borrador o enviado); el más reciente."""
        return self._group_orders().filtered(lambda o: o.state in ('draft', 'sent')).sorted('id')[-1:]

    def _add_lines_to_group_order(self, commands):
        """Añade las líneas al presupuesto abierto del grupo; si no hay ninguno lo crea (adicional si
        el anterior ya estaba confirmado). Devuelve (presupuesto, creado)."""
        self.ensure_one()
        order = self._open_group_order()
        if order:
            order.write({'order_line': commands})
            if order.state == 'sent':
                order.message_post(body=_(
                    'Se añadió «%s» a un presupuesto que ya se había enviado: reenvíalo al cliente'
                    ' para que lo vea actualizado.'
                ) % (self._event_label() or self.display_name))
            return order, False
        previous = self._group_orders().filtered(lambda o: o.state != 'cancel').sorted('id')[:1]
        order = self.env['sale.order'].create({
            'partner_id': self.lead_id.partner_id.id,
            'origin': self.lead_id.name,
            'opportunity_id': self.lead_id.id,
            'order_line': commands,
        })
        if previous:
            order.message_post(body=_(
                'Presupuesto adicional del grupo: el anterior (%s) ya estaba confirmado y no se modifica.'
            ) % previous.name)
        return order, True

    def _event_line_vals(self):
        event = self.event_id
        if not event:
            return {}
        return {'service_date': event.event_date, 'service_event_type_id': event.event_type_id.id}

    def _event_label(self):
        """'Cena · 16/11' -- vacío si la búsqueda no es de un evento."""
        event = self.event_id
        parts = [event.event_type_id.name, event.event_date and event.event_date.strftime('%d/%m')]
        return ' · '.join(part for part in parts if part)

    def _link_sale_order(self, order, line, created=True):
        self.sale_order_id = order.id
        if created:
            self.message_post_if_exists(_(
                'Presupuesto de venta %(name)s creado a partir de %(restaurant)s.'
            ) % {'name': order.name, 'restaurant': line.name})
        else:
            self.message_post_if_exists(_(
                '%(restaurant)s añadido al presupuesto de venta %(name)s del grupo.'
            ) % {'name': order.name, 'restaurant': line.name})

    def _apply_default_margin(self, cost_amount):
        """Precio al cliente = precio del restaurante + margen (20 % por defecto, ajustable en
        Ajustes → Restagrup). El margen nunca se muestra desglosado en la línea del cliente."""
        return self.env['restagrup.pricing'].apply_margin(cost_amount)

    def _action_view_sale_order(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('sale.action_orders')
        action['res_id'] = self.sale_order_id.id
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        return action
