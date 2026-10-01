# -*- coding: utf-8 -*-
from odoo import fields, models


class RestaurantSearchLine(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    partner_worked_with = fields.Boolean(
        related='partner_id.restaurant_worked_with', string='Ya trabajado con este',
    )

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for line in self:
            self.env['restagrup.restaurant.notice']._register_reply(line, msg_dict)
        return res
