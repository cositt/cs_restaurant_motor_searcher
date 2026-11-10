# -*- coding: utf-8 -*-
"""Al elegir en el enlace, la agencia puede escribir (si quiere) los platos o lo que necesite (ronda 09/11)."""
from markupsafe import Markup

from odoo import _, fields, models

MAX_NOTES = 2000


class RestaurantSearchLineAgencyNotes(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    agency_choice_notes = fields.Text(
        string='Lo que pidió la agencia', copy=False,
        help='Lo que escribió la agencia al elegir desde el enlace de la propuesta: platos, alergias,'
             ' observaciones.')


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
        if notes:
            line.agency_choice_notes = notes
        line._choose_line()
        body = Markup('%s') % _('La agencia ha elegido «%(name)s» para %(service)s desde el enlace de la propuesta.',
                                name=line.name, service=self._restagrup_service_label(search))
        if notes:
            body += Markup('<br/>%s <i>%s</i>') % (_('Escribió:'), notes)
        self.message_post(body=body, message_type='notification', subtype_xmlid='mail.mt_note')
        return True


class CrmLeadAgencyNotesToOrder(models.Model):
    _inherit = 'crm.lead'

    def action_create_joint_quote(self):
        """Lo que escribió la agencia al elegir pasa a «Observaciones» del pedido (salen en las confirmaciones)."""
        result = super().action_create_joint_quote()
        for lead in self:
            chosen = lead.restagrup_restaurant_search_ids.chosen_line_id.filtered('agency_choice_notes')
            orders = lead._restagrup_live_orders().filtered(lambda order: not order.restagrup_observations)
            if chosen and orders:
                orders.restagrup_observations = '\n'.join(
                    '%s: %s' % (line.name, line.agency_choice_notes) for line in chosen)
        return result
