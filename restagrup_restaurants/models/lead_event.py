# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class RestagrupLeadEvent(models.Model):
    _inherit = 'restagrup.lead.event'

    search_ids = fields.One2many('restagrup.restaurant.search', 'event_id', string='Búsquedas')

    def action_search_restaurants(self):
        """Búsqueda propia de este evento (ciudad, comensales…), colgando del mismo grupo. Si ya
        existe, se abre sin duplicarla."""
        self.ensure_one()
        search = self.search_ids[:1]
        if not search:
            if not self.city:
                raise UserError(_('Indica la ciudad del evento antes de buscar restaurantes.'))
            search = self.env['restagrup.restaurant.search'].create({
                'lead_id': self.lead_id.id,
                'event_id': self.id,
                'city': self.city,
                'min_capacity': self.pax,
            })
            search.action_search()
            self.state = 'searching'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search',
            'res_id': search.id,
            'view_mode': 'form',
            'target': 'current',
        }
