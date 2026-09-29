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
        if not self.lead_id.partner_id:
            raise UserError(_(
                'El grupo/cliente "%s" no tiene un contacto de facturación asignado'
                ' -- asígnalo antes de crear el presupuesto de venta.'
            ) % self.lead_id.name)

        product = self.env.ref('restagrup_service_orders.product_restaurant_service')
        order = self.env['sale.order'].create({
            'partner_id': self.lead_id.partner_id.id,
            'origin': self.lead_id.name,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': _('Servicio en %(restaurant)s — %(city)s, %(pax)s pax') % {
                    'restaurant': line.name,
                    'city': self.city or '',
                    'pax': self.min_capacity or '?',
                },
                'product_uom_qty': 1,
                'price_unit': self._apply_default_margin(line.quote_amount),
                'restaurant_id': line.partner_id.id,
                'restagrup_search_line_id': line.id,
            })],
        })
        self.sale_order_id = order.id
        self.message_post_if_exists(_(
            'Presupuesto de venta %(name)s creado a partir de %(restaurant)s.'
        ) % {'name': order.name, 'restaurant': line.name})
        return self._action_view_sale_order()

    def _apply_default_margin(self, cost_amount):
        """Precio de venta = coste × (1 + margen/100) -- el margen es global
        (Ajustes > Restagrup), nunca se muestra desglosado al cliente en la línea.
        Sin margen configurado, el precio de venta sale igual al coste (0%)."""
        margin_percent = self.env['ir.config_parameter'].sudo().get_param(
            'restagrup.default_margin_percent', 0,
        )
        try:
            margin_percent = float(margin_percent or 0)
        except ValueError:
            margin_percent = 0.0
        return cost_amount * (1 + margin_percent / 100)

    def _action_view_sale_order(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('sale.action_orders')
        action['res_id'] = self.sale_order_id.id
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        return action
