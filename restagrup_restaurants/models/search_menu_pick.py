# -*- coding: utf-8 -*-
"""Ver los menús de un restaurante desde su tarjeta del buscador y pedir disponibilidad de uno concreto, como el
«ojo» del CRM de Restagrup (PPT de Conchita 2026-11-04, diapositiva 5)."""
from odoo import _, models
from odoo.exceptions import UserError

LINE_CONTEXT_KEY = 'restagrup_search_line_id'


class RestaurantSearchLineMenus(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def action_view_menus(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Añade primero el restaurante como contacto: los menús se guardan en su ficha.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('Menús de %s') % self.partner_id.name,
            'res_model': 'restagrup.restaurant.menu', 'view_mode': 'list,form',
            'views': [(self.env.ref('restagrup_restaurants.view_restaurant_menu_pick_list').id, 'list'),
                      (False, 'form')],
            'domain': [('partner_id', '=', self.partner_id.id)],
            'context': {LINE_CONTEXT_KEY: self.id, 'default_partner_id': self.partner_id.id},
            'target': 'new',
        }


class RestaurantMenuPick(models.Model):
    _inherit = 'restagrup.restaurant.menu'

    def action_request_quote_with_menu(self):
        """Pide disponibilidad de este menú: el correo al restaurante lleva sus platos y su precio de coste."""
        self.ensure_one()
        line = self.env['restagrup.restaurant.search.line'].browse(self.env.context.get(LINE_CONTEXT_KEY)).exists()
        if not line:
            raise UserError(_('Abre los menús desde la tarjeta del restaurante en el buscador.'))
        if line.partner_id != self.partner_id:
            raise UserError(_('Este menú es de otro restaurante.'))
        line.menu_id = self
        line.action_request_quote()
        return {'type': 'ir.actions.act_window_close', 'infos': {'reload': True}}
