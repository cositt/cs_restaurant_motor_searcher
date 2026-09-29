# -*- coding: utf-8 -*-
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
