# -*- coding: utf-8 -*-
import json

from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_restaurant_search_ids = fields.One2many(
        'restagrup.restaurant.search', 'lead_id', string='Búsquedas de restaurantes',
    )
    restagrup_restaurant_search_count = fields.Integer(
        string='Nº búsquedas', compute='_compute_restagrup_restaurant_search_count',
    )

    def _compute_restagrup_restaurant_search_count(self):
        for lead in self:
            lead.restagrup_restaurant_search_count = len(lead.restagrup_restaurant_search_ids)

    def _restagrup_review_extraction(self):
        """Empezar a buscar restaurantes es la revisión humana de la extracción de la IA: se confirma si los
        datos del lead siguen como los propuso, y se marca como corregida si alguien los cambió."""
        for lead in self:
            log = self.env['restagrup.ai.log']._pending('lead_extraction', lead)
            if not log:
                continue
            data = json.loads(log.output or '{}')
            first = (lead._restagrup_event_vals_list(data) or [{}])[0]
            city = (data.get('ciudad') or first.get('city') or '') or False
            pax = lead._restagrup_safe_int(data.get('num_pax') or first.get('pax'))
            same = (lead.restagrup_city or False) == city and lead.restagrup_pax == pax
            log._close('confirmed' if same else 'corrected')

    def action_view_restaurant_searches(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Búsquedas de restaurantes',
            'res_model': 'restagrup.restaurant.search',
            'domain': [('lead_id', '=', self.id)],
            'context': {
                'default_lead_id': self.id,
                'default_city': self.restagrup_city,
                'default_min_capacity': self.restagrup_pax,
            },
        }
        if self.restagrup_restaurant_search_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.restagrup_restaurant_search_ids.id,
            })
        else:
            action['view_mode'] = 'list,form'
        return action

    def action_search_all_events(self):
        """Una búsqueda por cada evento en borrador que ya tenga ciudad; los que ya tienen búsqueda
        no se duplican."""
        self.ensure_one()
        for event in self.restagrup_event_ids.filtered(lambda e: e.state == 'draft' and e.city):
            event.action_search_restaurants()
        return self.action_view_restaurant_searches()

    def action_search_restaurants(self):
        self.ensure_one()
        if not self.restagrup_city:
            return self.action_view_restaurant_searches()
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.id,
            'city': self.restagrup_city or '',
            'min_capacity': self.restagrup_pax,
        })
        search.action_search()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search',
            'res_id': search.id,
            'view_mode': 'form',
            'target': 'current',
        }
