# -*- coding: utf-8 -*-
"""Ver los menús de un restaurante desde su tarjeta del buscador y pedir disponibilidad de uno concreto, como el
«ojo» del CRM de Restagrup (PPT de Conchita 2026-11-04, diapositiva 5)."""
from odoo import _, models
from odoo.exceptions import UserError

LINE_CONTEXT_KEY = 'restagrup_search_line_id'
OFFER_KEY = 'restagrup_offer_menu_line_id'  # tarjeta desde la que se ofrece otro menú (reunión 13/11, P8)
REPLACE_KEY = 'restagrup_offer_menu_replace'  # el menú elegido va a esa misma tarjeta (P10)


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


    def _free_saved_menus(self):
        """Menús de su ficha que aún no tiene ninguna tarjeta viva de este restaurante en la búsqueda."""
        self.ensure_one()
        cards = self.search_id.line_ids.filtered(
            lambda line: line.partner_id == self.partner_id and line.etiqueta != 'descartado')
        return self._catalog_menus() - cards.menu_id

    def _menu_picker_action(self, menus, replace=False):
        return {
            'type': 'ir.actions.act_window', 'name': _('Elige otro menú de %s') % self.partner_id.name,
            'res_model': 'restagrup.restaurant.menu', 'view_mode': 'list',
            'views': [(self.env.ref('restagrup_restaurants.view_restaurant_menu_offer_list').id, 'list')],
            'domain': [('id', 'in', menus.ids)],
            'context': {OFFER_KEY: self.id, REPLACE_KEY: replace, 'create': False},
            'target': 'new',
        }

    def action_offer_other_menu(self):
        """Reunión 12/11 (5.7/5.6): otra tarjeta del mismo restaurante para otro menú con su precio; en la
        propuesta sale una opción por menú. Reunión 13/11 (P8): si tiene menús guardados libres, se elige uno de
        ellos; si no, tarjeta en blanco («Visto») para registrar la respuesta del restaurante."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Añade primero el restaurante como contacto: los menús se guardan en su ficha.'))
        menus = self._free_saved_menus()
        if menus:
            return self._menu_picker_action(menus)
        other = self._blank_menu_card()
        action = other.action_open_quote_form()
        action['name'] = _('Otro menú de %s') % self.name
        return action

    def _offer_saved_menu(self, menu, replace=False):
        """Pone `menu` con su precio de catálogo en esta tarjeta (replace) o en una tarjeta nueva del restaurante."""
        self.ensure_one()
        card = self if replace else self._blank_menu_card()
        card._apply_catalog_quote(menu)
        return card

    def action_remove_menu(self):
        """Reunión 13/11 (P10): quitar un menú sin perder el restaurante. Con otra tarjeta suya en la búsqueda se
        descarta esta; si es la única, vuelve a «Interesado» sin menú ni precio y se abre la lista de sus menús
        para elegir otro."""
        self.ensure_one()
        others = self.search_id.line_ids.filtered(
            lambda line: line != self and line.partner_id == self.partner_id and line.etiqueta != 'descartado')
        if others:
            self.action_mark_descartado()
            return True
        if self.search_id.chosen_line_id == self:
            self.search_id.chosen_line_id = False
        self.search_id.message_post_if_exists(_('%(name)s: quitado el menú %(menu)s (%(price)s).') % {
            'name': self.name, 'menu': self.menu_id.name or '—', 'price': self._quote_price_text()})
        self.write({
            'etiqueta': 'interesado', 'menu_id': False, 'quote_price_pp': 0.0, 'quote_amount': 0.0,
            'quote_received_date': False, 'quote_availability_pending': False,
        })
        menus = self._free_saved_menus()
        return self._menu_picker_action(menus, replace=True) if menus else True

    def _blank_menu_card(self):
        self.ensure_one()
        other = self.copy({
            'etiqueta': 'visto', 'menu_id': False, 'quote_price_pp': 0.0, 'quote_amount': 0.0, 'quote_notes': False,
            'quote_raw_text': False, 'quote_received_date': False, 'quote_requested_date': False,
            'quote_reminder_sent_date': False, 'quote_availability_pending': False, 'sequence': self.sequence,
        })
        self.search_id.message_post_if_exists(_('%s: otra tarjeta para ofrecer otro menú.') % self.name)
        return other


class RestaurantMenuPick(models.Model):
    _inherit = 'restagrup.restaurant.menu'

    def action_offer_this_menu(self):
        """Reunión 13/11 (P8/P10): elegido en la lista de «+ Otro menú» / «Quitar este menú»."""
        self.ensure_one()
        line = self.env['restagrup.restaurant.search.line'].browse(self.env.context.get(OFFER_KEY)).exists()
        if not line:
            raise UserError(_('Abre la lista desde la tarjeta del restaurante en el buscador.'))
        if line.partner_id != self.partner_id:
            raise UserError(_('Este menú es de otro restaurante.'))
        line._offer_saved_menu(self, replace=bool(self.env.context.get(REPLACE_KEY)))
        return {'type': 'ir.actions.act_window_close'}

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
