# -*- coding: utf-8 -*-
"""Al elegir en el enlace, la agencia puede escribir (si quiere) los platos o lo que necesite (ronda 09/11)."""
import difflib
import re
import unicodedata

from markupsafe import Markup

from odoo import _, fields, models

MAX_NOTES = 2000
# Reunión 12/11 (8.5): parecido mínimo para dar por buena una errata («sopa de fidos» -> «Sopa de fideos»).
DISH_MATCH_RATIO = 0.75
BULLET = re.compile(r'^\s*(?:[-*•·]|\d+[.)])\s*')


def _dish_key(text):
    text = unicodedata.normalize('NFKD', (text or '').casefold())
    return ' '.join(''.join(char for char in text if not unicodedata.combining(char)).split())


class RestaurantSearchLineAgencyNotes(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    agency_choice_notes = fields.Text(
        string='Lo que pidió la agencia', copy=False,
        help='Lo que escribió la agencia al elegir desde el enlace de la propuesta: platos, alergias,'
             ' observaciones.')


class RestaurantSearchLineChosenDishes(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def _restagrup_match_dish(self, written, dishes):
        """El plato del menú que la agencia quiso escribir, o None si no se parece a ninguno."""
        key = _dish_key(written)
        by_key = {_dish_key(dish): dish for dish in dishes}
        if key in by_key:
            return by_key[key]
        prefixed = [dish for dish_key, dish in by_key.items() if dish_key.startswith(key + ' ')]
        if len(prefixed) == 1:
            return prefixed[0]  # «Pollo» -> «Pollo asado»
        close = difflib.get_close_matches(key, list(by_key), n=1, cutoff=DISH_MATCH_RATIO)
        return by_key[close[0]] if close else None

    def _restagrup_check_chosen_dishes(self, notes):
        """Reunión 12/11 (8.5): compara lo elegido con los platos del menú. Devuelve (texto con las erratas
        corregidas, [(escrito, plato)] corregidos, [escrito] que no están en el menú). Sin menú detallado, nada."""
        self.ensure_one()
        notes = (notes or '').replace('\r\n', '\n').replace('\r', '\n')
        dishes = self.menu_id.line_ids.mapped('name')
        if not dishes:
            return notes, [], []
        lines, fixed, unknown = [], [], []
        for raw in notes.split('\n'):
            bullet = BULLET.match(raw)
            prefix, written = (raw[:bullet.end()], raw[bullet.end():]) if bullet else ('', raw)
            written = written.strip()
            if not written:
                lines.append(raw)
                continue
            dish = self._restagrup_match_dish(written, dishes)
            if dish is None:
                unknown.append(written)
            elif dish != written:
                fixed.append((written, dish))
                written = dish
            lines.append(prefix + written)
        return '\n'.join(lines), fixed, unknown


class CrmLeadPortalChoice(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_portal_choose(self, search_id, line_id, dishes=None):
        """La agencia elige desde el enlace: solo un restaurante de la propuesta de ese servicio y solo si aún no
        hay elegido. Lo que escriba se guarda en el presupuesto elegido y queda en el historial del grupo."""
        self.ensure_one()
        search = self.restagrup_restaurant_search_ids.filtered(lambda s: str(s.id) == str(search_id))
        if not search or search.chosen_line_id:
            return False
        line = next((row['line'] for row in search.restagrup_comparison_rows()
                     if str(row['line'].id) == str(line_id)), None)
        if not line:
            return False
        notes = (dishes or '').strip()[:MAX_NOTES]
        fixed, unknown = [], []
        if notes:
            notes, fixed, unknown = line._restagrup_check_chosen_dishes(notes)
            line.agency_choice_notes = notes
        line._choose_line()
        body = Markup('%s') % _('La agencia ha elegido «%(name)s» para %(service)s desde el enlace de la propuesta.',
                                name=line.name, service=self._restagrup_service_label(search))
        if notes:
            body += Markup('<br/>%s <i>%s</i>') % (_('Escribió:'), notes)
        self.message_post(body=body, message_type='notification', subtype_xmlid='mail.mt_note')
        self._restagrup_note_dish_check(line, fixed, unknown)
        return True

    def _restagrup_note_dish_check(self, line, fixed, unknown):
        if fixed:
            self.message_post(body=_('Platos corregidos al elegir (erratas): %s.') % ', '.join(
                '«%s» → «%s»' % pair for pair in fixed), subtype_xmlid='mail.mt_note')
        if unknown:
            self.message_post(body=_('%(dishes)s no está en el menú «%(menu)s» de %(restaurant)s: confírmalo con la'
                                     ' agencia antes de enviar la confirmación.') % {
                'dishes': ', '.join('«%s»' % dish for dish in unknown), 'menu': line.menu_id.name,
                'restaurant': line.name}, subtype_xmlid='mail.mt_note')


class CrmLeadAgencyNotesToOrder(models.Model):
    _inherit = 'crm.lead'

    def action_create_joint_quote(self):
        """Lo que escribió la agencia al elegir pasa a «Observaciones» del pedido (salen en las confirmaciones).
        Ronda 11/11: si eligió del menú del catálogo, eso ya sale en el servicio como «Platos elegidos» y no se
        repite en las observaciones."""
        result = super().action_create_joint_quote()
        for lead in self:
            chosen = lead.restagrup_restaurant_search_ids.chosen_line_id.filtered(
                lambda line: line.agency_choice_notes and not line.menu_id)
            orders = lead._restagrup_live_orders().filtered(lambda order: not order.restagrup_observations)
            if chosen and orders:
                orders.restagrup_observations = '\n'.join(
                    '%s: %s' % (line.name, line.agency_choice_notes) for line in chosen)
        return result
