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


    def action_offer_other_menu(self):
        """Reunión 12/11 (5.7/5.6): otra tarjeta del mismo restaurante para registrar otro menú con su precio; en
        la propuesta sale una opción por menú y ninguno pisa el precio del otro. Queda como «Visto» (sin
        recordatorios ni petición a interesados) hasta registrar el menú."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Añade primero el restaurante como contacto: los menús se guardan en su ficha.'))
        other = self.copy({
            'etiqueta': 'visto', 'menu_id': False, 'quote_price_pp': 0.0, 'quote_amount': 0.0, 'quote_notes': False,
            'quote_raw_text': False, 'quote_received_date': False, 'quote_requested_date': False,
            'quote_reminder_sent_date': False, 'quote_availability_pending': False, 'sequence': self.sequence,
        })
        self.search_id.message_post_if_exists(_('%s: otra tarjeta para ofrecer otro menú.') % self.name)
        action = other.action_open_quote_form()
        action['name'] = _('Otro menú de %s') % self.name
        return action


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
        return line.action_open_quote_request()  # reunión 12/11 (4.1): se revisa antes de enviar
