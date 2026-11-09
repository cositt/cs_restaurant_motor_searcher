# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Ficha de agencia como la del CRM de Restagrup (notas de Conchita 05/11): datos adicionales.
    agency_trade_name = fields.Char(string='Nombre comercial')
    agency_payment_mode = fields.Selection(
        [('prepago', 'Prepago'), ('credito', 'Crédito')], string='Forma de pago', default='prepago',
        help='Prepago: paga antes del servicio para recibir el bono. Crédito: se le factura después.',
    )

    restaurant_purchase_order_ids = fields.One2many(
        'purchase.order', 'partner_id', string='Hojas de servicio (pedidos de compra)',
    )
    menu_ids = fields.One2many(
        'product.template', 'restaurant_id', string='Menús',
        help='Menús de este restaurante: productos de servicio con su precio de venta.',
    )
    restaurant_worked_with = fields.Boolean(
        string='Ya hemos trabajado con este restaurante', compute='_compute_restaurant_worked_with',
        help='Se marca solo cuando existe al menos una hoja de servicio real (pedido'
             ' de compra) con este restaurante -- nunca solo por haberlo elegido.',
    )

    @api.depends('restaurant_purchase_order_ids.state')
    def _compute_restaurant_worked_with(self):
        for partner in self:
            partner.restaurant_worked_with = bool(
                partner.sudo().restaurant_purchase_order_ids.filtered(lambda po: po.state != 'cancel')
            )

    @api.model
    def restagrup_action_agencies(self):
        """Menú «Agencias»: las empresas que nos piden grupos. Son todas las empresas que no son restaurantes
        ni nuestra propia compañía; así salen también las creadas a mano, sin marcarlas de ninguna forma."""
        own = self.env['res.company'].sudo().search([]).partner_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agencias'),
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'views': [(self.env.ref('restagrup_service_orders.view_partner_agency_list').id, 'list'), (False, 'form')],
            'domain': [('is_company', '=', True), ('is_restaurant', '=', False), ('id', 'not in', own.ids)],
            'context': {'default_is_company': True, 'default_company_type': 'company'},
            'help': _('<p class="o_view_nocontent_smiling_face">Todavía no hay agencias</p>'
                      '<p>Aquí están las agencias con sus datos de facturación y sus contactos.</p>'),
        }
