# -*- coding: utf-8 -*-
"""Beneficio arriba en el expediente (notas de Conchita 05/11): total a la agencia, total a los restaurantes y
comisión de Restagrup. Con restaurantes en otra moneda, el beneficio de la reserva frente al de hoy, como en su CRM
(en verde si se gana, en rojo si se pierde)."""
from odoo import api, fields, models


class CrmLeadProfit(models.Model):
    _inherit = 'crm.lead'

    restagrup_currency_id = fields.Many2one(
        'res.currency', compute='_compute_restagrup_profit', string='Moneda de los totales')
    restagrup_total_agency = fields.Monetary(
        string='Total agencia', currency_field='restagrup_currency_id', compute='_compute_restagrup_profit',
        help='Lo que paga la agencia (IVA incluido), sumando los presupuestos no cancelados del grupo.')
    restagrup_total_restaurants = fields.Monetary(
        string='Total restaurantes', currency_field='restagrup_currency_id', compute='_compute_restagrup_profit',
        help='Lo que se paga a los restaurantes.')
    restagrup_total_commission = fields.Monetary(
        string='Comisión', currency_field='restagrup_currency_id', compute='_compute_restagrup_profit',
        help='Beneficio de Restagrup: lo que paga la agencia menos lo que cobran los restaurantes.')
    restagrup_has_fx = fields.Boolean(string='Restaurantes en otra moneda', compute='_compute_restagrup_profit')
    restagrup_fx_booked_profit = fields.Monetary(
        string='Beneficio de la reserva', currency_field='restagrup_currency_id', compute='_compute_restagrup_profit')
    restagrup_fx_current_profit = fields.Monetary(
        string='Beneficio con el cambio de hoy', currency_field='restagrup_currency_id',
        compute='_compute_restagrup_profit')
    restagrup_fx_delta = fields.Monetary(
        string='Variación por la moneda', currency_field='restagrup_currency_id', compute='_compute_restagrup_profit',
        help='Beneficio con el cambio de hoy menos el de la reserva. En negativo, la moneda del restaurante ha'
             ' subido: avisar a la agencia.')

    def _restagrup_profit_orders(self):
        self.ensure_one()
        orders = self.sudo().order_ids | self.restagrup_restaurant_search_ids.sudo().sale_order_id
        return orders.filtered(lambda o: o.state != 'cancel')

    @api.depends('order_ids.state', 'order_ids.amount_total', 'order_ids.order_line.restagrup_unit_cost',
                 'order_ids.order_line.restagrup_fx_rate', 'restagrup_restaurant_search_ids.sale_order_id')
    def _compute_restagrup_profit(self):
        for lead in self:
            orders = lead._restagrup_profit_orders()
            lines = orders.order_line.filtered(lambda l: not l.display_type and l.restagrup_unit_cost)
            booked = sum(orders.mapped('restagrup_margin_total'))
            fx_lines = lines.filtered(lambda l: l.restagrup_fx_currency_code and l.restagrup_fx_rate)
            delta = sum((line.restagrup_unit_cost - line._restagrup_fx_current_cost()) * line.product_uom_qty
                        for line in fx_lines)
            lead.restagrup_currency_id = orders[:1].currency_id or self.env.company.currency_id
            lead.restagrup_total_agency = sum(orders.mapped('amount_total'))
            lead.restagrup_total_restaurants = sum(orders.mapped('restagrup_cost_total'))
            lead.restagrup_total_commission = booked
            lead.restagrup_has_fx = bool(fx_lines)
            lead.restagrup_fx_booked_profit = booked
            lead.restagrup_fx_current_profit = booked + delta
            lead.restagrup_fx_delta = round(delta, 2)

    def action_restagrup_refresh_fx(self):
        """«Actualizar cambio»: trae el cambio de hoy del BCE para las monedas de los restaurantes del grupo."""
        exchange = self.env['restagrup.exchange']
        codes = set()
        for lead in self:
            codes |= set(filter(None, lead._restagrup_profit_orders().order_line.mapped('restagrup_fx_currency_code')))
        currencies = self.env['res.currency'].with_context(active_test=False).search([('name', 'in', list(codes))])
        exchange.refresh_rates(currencies)
        return True
