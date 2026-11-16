# -*- coding: utf-8 -*-
"""El precio estimado del servicio en el buscador (PPT de Conchita 2026-11-04, diapositiva 2): ordena los
restaurantes por cercanía a ese precio y avisa de los que se salen. El precio de cada restaurante es el de su
presupuesto (con la comisión) o, si aún no hay, el de su menú más barato."""
from odoo import _, api, fields, models

PRICE_TOLERANCE = 0.15  # por encima de un 15 % del estimado, se avisa
PRICE_LEVELS = [('ok', 'Dentro del estimado'), ('near', 'Justo (hasta +15 %)'), ('over', 'Se pasa del estimado')]
PRICE_CONFIRMED_KEY = 'restagrup_price_confirmed'
PRICE_CHECK_KEY = 'restagrup_price_check'  # lo ponen los botones «Elegir» de la pantalla


def _euros(amount):
    return ('%.2f' % amount).replace('.', ',')


class RestaurantSearchBudget(models.Model):
    _inherit = 'restagrup.restaurant.search'

    budget_pp = fields.Float(
        related='event_id.budget_pp', string='Precio estimado (€/pers.)',
        help='El precio por persona del servicio (el que dijo la agencia o el del baremo). Ordena los restaurantes'
             ' y avisa de los que se salen.')
    sort_by = fields.Selection(selection_add=[('budget_near', 'Cercanía al precio estimado'),
                                              ('agency_price_asc', 'Precio por persona: más barato primero')],
                               ondelete={'budget_near': 'set default', 'agency_price_asc': 'set default'})
    # Reunión 13/11 (P2): los resultados en tarjetas o en tabla (la tabla es la misma lista de restaurantes).
    results_view = fields.Selection([('cards', 'Tarjetas'), ('table', 'Tabla')], string='Ver resultados en',
                                    default='cards', required=True)
    line_table_ids = fields.One2many('restagrup.restaurant.search.line', 'search_id', string='Resultados (tabla)')

    def _sort_key_for(self, sort_by):
        if sort_by == 'agency_price_asc':
            # precio real a la agencia (presupuesto o menú más barato); sin precio, al final
            return (lambda line: (not line.known_price_pp, line.known_price_pp or 0)), False
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
    # Reunión 13/11 (P9): semáforo frente al precio estimado; sin estimado o sin precio, sin color.
    price_level_status = fields.Selection(PRICE_LEVELS, string='Precio frente al estimado',
                                          compute='_compute_price_warning')

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
            line.price_level_status = (
                False if not (price and budget) else 'ok' if price <= budget else 'over' if over else 'near')
            line.price_warning = _('Se sale del precio estimado: %(price)s €/pers. (estimado %(budget)s €)') % {
                'price': _euros(price), 'budget': _euros(budget)} if over else False

    def _price_over_text(self):
        self.ensure_one()
        budget = self.search_id.budget_pp
        return _('Se pasa %(diff)s €/pers. del precio estimado: %(price)s €/pers. frente a %(budget)s €.') % {
            'diff': _euros(self.known_price_pp - budget), 'price': _euros(self.known_price_pp), 'budget': _euros(budget)}

    def action_toggle_chosen(self):
        """Reunión 13/11 (P9): elegir desde la pantalla uno que se pasa del estimado pide confirmación (no lo
        impide). Las elecciones automáticas (portal de la agencia, cambio de restaurante) no preguntan."""
        self.ensure_one()
        context = self.env.context
        choosing = self.search_id.chosen_line_id != self
        if (choosing and self.price_level_status == 'over' and context.get(PRICE_CHECK_KEY)
                and not context.get(PRICE_CONFIRMED_KEY)):
            wizard = self.env['restagrup.choose.over.budget'].create({
                'line_id': self.id, 'message': self._price_over_text()})
            return {
                'type': 'ir.actions.act_window', 'name': _('¿Elegir igualmente?'),
                'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
            }
        return super().action_toggle_chosen()


class ChooseOverBudget(models.TransientModel):
    _name = 'restagrup.choose.over.budget'
    _description = 'Confirmar restaurante que se pasa del precio estimado'

    line_id = fields.Many2one('restagrup.restaurant.search.line', required=True, ondelete='cascade')
    message = fields.Char(readonly=True)

    def action_confirm(self):
        self.ensure_one()
        line = self.line_id
        result = line.with_context(**{PRICE_CONFIRMED_KEY: True}).action_toggle_chosen()
        if line.search_id.chosen_line_id == line:
            line.search_id.message_post_if_exists(_('%(name)s elegido aunque se pasa del precio estimado. %(text)s') % {
                'name': line.name, 'text': self.message})
        return result or {'type': 'ir.actions.act_window_close'}
