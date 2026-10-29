# -*- coding: utf-8 -*-
from odoo import Command, _, fields, models
from odoo.exceptions import UserError


class ApproxOptionsWizard(models.TransientModel):
    """Elegir restaurantes y menús guardados para mandar a la agencia opciones orientativas mientras faltan datos."""
    _name = 'restagrup.approx.options.wizard'
    _description = 'Añadir opciones orientativas'

    pending_id = fields.Many2one('restagrup.pending.mail', required=True, ondelete='cascade')
    city = fields.Char(string='Ciudad', help='Vacío: menús de cualquier ciudad.')
    pax = fields.Integer(string='Comensales', help='Deja fuera los restaurantes y menús sin capacidad para el grupo.')
    season = fields.Integer(string='Temporada', default=lambda self: fields.Date.context_today(self).year)
    show_restaurants = fields.Boolean(string='Mostrar restaurantes', default=True)
    line_ids = fields.One2many('restagrup.approx.options.wizard.line', 'wizard_id', string='Menús')

    def _create_for(self, pending):
        event = pending.request_lead_id.restagrup_event_ids.filtered('city')[:1] or pending.request_lead_id.restagrup_event_ids[:1]
        wizard = self.create({
            'pending_id': pending.id,
            'city': event.city or pending.request_lead_id.restagrup_city or '',
            'pax': event.pax or pending.request_lead_id.restagrup_pax or 0,
            'show_restaurants': pending.option_show_restaurants if pending.option_ids else True,
        })
        wizard._rebuild_lines(selected=pending.option_ids.menu_id)
        return wizard

    def _candidate_menus(self):
        """Menús de la temporada con sitio para el grupo, del más barato al más caro. Un aforo o capacidad sin
        rellenar no excluye: no se sabe."""
        self.ensure_one()
        domain = [('season', '=', self.season), ('partner_id.is_restaurant', '=', True)]
        if self.city:
            domain.append(('partner_id.city', '=ilike', self.city.strip()))
        menus = self.env['restagrup.restaurant.menu'].search(domain)
        if self.pax:
            menus = menus.filtered(lambda m: (
                (not m.partner_id.restaurant_capacity or m.partner_id.restaurant_capacity >= self.pax)
                and (not m.max_pax or m.max_pax >= self.pax)
                and (not m.min_pax or m.min_pax <= self.pax)))
        return menus.sorted(lambda m: (m.sale_price, m.id))

    def _rebuild_lines(self, selected):
        """Rehace la lista con los filtros actuales. Lo marcado se conserva aunque ya no pase el filtro."""
        menus = self._candidate_menus()
        menus |= selected - menus
        self.line_ids = [Command.clear()] + [
            Command.create({'menu_id': menu.id, 'selected': menu in selected}) for menu in menus]

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
            'view_mode': 'form', 'target': 'new', 'name': _('Opciones orientativas'),
        }

    def action_refresh(self):
        self.ensure_one()
        self._rebuild_lines(selected=self.line_ids.filtered('selected').menu_id)
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        menus = self.line_ids.filtered('selected').menu_id
        if not menus:
            raise UserError(_('Marca al menos un menú para añadirlo como opción.'))
        self.pending_id._set_approx_options(menus, self.show_restaurants)
        return {'type': 'ir.actions.act_window_close'}


class ApproxOptionsWizardLine(models.TransientModel):
    _name = 'restagrup.approx.options.wizard.line'
    _description = 'Menú candidato a opción orientativa'
    _order = 'price_per_person, id'

    wizard_id = fields.Many2one('restagrup.approx.options.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Incluir')
    menu_id = fields.Many2one('restagrup.restaurant.menu', string='Menú', required=True, ondelete='cascade')
    partner_id = fields.Many2one(related='menu_id.partner_id', string='Restaurante')
    city = fields.Char(related='menu_id.partner_id.city', string='Ciudad')
    capacity = fields.Integer(related='menu_id.partner_id.restaurant_capacity', string='Aforo')
    menu_type = fields.Selection(related='menu_id.menu_type')
    currency_id = fields.Many2one(related='menu_id.currency_id')
    price_per_person = fields.Monetary(related='menu_id.sale_price', string='Precio por persona', store=True)
