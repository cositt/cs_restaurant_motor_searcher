# -*- coding: utf-8 -*-
"""Hallazgo al capturar la guía (13/11): si la agencia eligió un plato que no está en el menú, la nota en el
historial se pasaba por alto. Ahora el cortafuegos lo recuerda antes de enviar las confirmaciones."""
from odoo import _, models


class RestaurantSearchLineDishWarning(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def _restagrup_dishes_not_in_menu_text(self):
        """«"Lubina" no está en el menú "X" de Casa Y» por cada línea con platos elegidos fuera del menú."""
        texts = []
        for line in self.filtered(lambda l: l.menu_id and l.agency_choice_notes):
            _notes, _fixed, unknown = line._restagrup_check_chosen_dishes(line.agency_choice_notes)
            if unknown:
                texts.append(_('%(dishes)s no está en el menú «%(menu)s» de %(restaurant)s', dishes=', '.join(
                    '«%s»' % dish for dish in unknown), menu=line.menu_id.name, restaurant=line.name))
        return texts

    def _restagrup_dish_firewall_message(self):
        texts = self._restagrup_dishes_not_in_menu_text()
        if not texts:
            return False
        return _('Platos elegidos que no están en el menú: %s. Confírmalo con la agencia y el restaurante.') % (
            '; '.join(texts))


class SaleOrderDishFirewall(models.Model):
    _inherit = 'sale.order'

    def _fw_dishes_in_menu(self):
        return self.order_line.restagrup_search_line_id._restagrup_dish_firewall_message()


class PurchaseOrderDishFirewall(models.Model):
    _inherit = 'purchase.order'

    def _fw_dishes_in_menu_restaurant(self):
        lines = self.order_line.restagrup_sale_line_id.restagrup_search_line_id
        return lines._restagrup_dish_firewall_message()
