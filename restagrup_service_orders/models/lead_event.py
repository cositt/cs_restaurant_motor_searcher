# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RestagrupLeadEvent(models.Model):
    _inherit = 'restagrup.lead.event'

    chosen_restaurant_id = fields.Many2one(
        'res.partner', string='Restaurante elegido', compute='_compute_chosen')
    # Punto 6 (reunión 12/11): ellos hablan del «menú de 16,80 €», no del total del grupo ni de lo que cobra el
    # restaurante. El total queda como columna opcional.
    chosen_price_pp = fields.Float(
        string='Precio menú (€/pers.)', digits=(16, 2), compute='_compute_chosen',
        help='Precio por persona que paga la agencia (restaurante + comisión), del restaurante elegido.')
    chosen_amount = fields.Float(string='Total restaurante (€)', compute='_compute_chosen')
    sale_order_id = fields.Many2one('sale.order', string='Presupuesto de venta', compute='_compute_chosen')
    sheet_state = fields.Char(string='Hoja de servicio', compute='_compute_chosen')

    @api.depends(
        'search_ids.chosen_line_id', 'search_ids.chosen_line_id.quote_client_price_per_person',
        'search_ids.sale_order_id',
        'search_ids.sale_order_id.restaurant_po_ids.restagrup_response_state',
    )
    def _compute_chosen(self):
        labels = dict(self.env['purchase.order']._fields['restagrup_response_state'].selection)
        for event in self:
            search = event.search_ids[:1]
            chosen = search.chosen_line_id
            order = search.sale_order_id
            sheet = order.sudo().restaurant_po_ids.filtered(
                lambda po: po.partner_id == chosen.partner_id and po.state != 'cancel')[:1] if order and chosen else False
            event.chosen_restaurant_id = chosen.partner_id
            event.chosen_price_pp = chosen.quote_client_price_per_person
            event.chosen_amount = chosen.quote_amount
            event.sale_order_id = order
            event.sheet_state = (
                labels.get(sheet.restagrup_response_state) or 'Sin respuesta' if sheet else False
            )
