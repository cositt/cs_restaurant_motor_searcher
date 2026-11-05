# -*- coding: utf-8 -*-
"""El precio estimado del servicio en el buscador (PPT de Conchita 2026-11-04, diapositiva 2): ordena los
restaurantes por cercanía a ese precio y avisa de los que se salen. El precio de cada restaurante es el de su
presupuesto (con la comisión) o, si aún no hay, el de su menú más barato."""
from odoo import _, api, fields, models

PRICE_TOLERANCE = 0.15  # por encima de un 15 % del estimado, se avisa


def _euros(amount):
    return ('%.2f' % amount).replace('.', ',')


class RestaurantSearchBudget(models.Model):
    _inherit = 'restagrup.restaurant.search'

    budget_pp = fields.Float(
        related='event_id.budget_pp', string='Precio estimado (€/pers.)',
        help='El precio por persona del servicio (el que dijo la agencia o el del baremo). Ordena los restaurantes'
             ' y avisa de los que se salen.')
    sort_by = fields.Selection(selection_add=[('budget_near', 'Cercanía al precio estimado')],
                               ondelete={'budget_near': 'set default'})

    def _sort_key_for(self, sort_by):
        if sort_by == 'budget_near':
            budget = self.budget_pp
            return (lambda line: (not line.known_price_pp, abs((line.known_price_pp or 0) - budget))), False
        return super()._sort_key_for(sort_by)

    def action_search(self):
        result = super().action_search()
        if self.budget_pp and self.sort_by in (False, 'default'):
            self.sort_by = 'budget_near'
        if self.sort_by == 'budget_near':
            self.action_apply_sort()
        return result


class RestaurantSearchLineBudget(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    known_price_pp = fields.Float(
        string='Precio a la agencia (€/pers.)', compute='_compute_price_warning',
        help='El de su presupuesto con nuestra comisión o, si aún no hay, el de su menú más barato.')
    price_warning = fields.Char(string='Aviso de precio', compute='_compute_price_warning')

    @api.depends('quote_price_pp', 'quote_client_price_per_person', 'partner_id', 'search_id.budget_pp')
    def _compute_price_warning(self):
        menus = self.env['restagrup.restaurant.menu'].search(
            [('partner_id', 'in', self.partner_id.ids), ('sale_price', '>', 0)])
        cheapest = {}
        for menu in menus:
            current = cheapest.get(menu.partner_id.id)
            cheapest[menu.partner_id.id] = min(current, menu.sale_price) if current else menu.sale_price
        for line in self:
            price = line.quote_client_price_per_person if line.quote_price_pp else cheapest.get(line.partner_id.id, 0.0)
            budget = line.search_id.budget_pp
            line.known_price_pp = price
            over = price and budget and price > budget * (1 + PRICE_TOLERANCE)
            line.price_warning = _('Se sale del precio estimado: %(price)s €/pers. (estimado %(budget)s €)') % {
                'price': _euros(price), 'budget': _euros(budget)} if over else False
