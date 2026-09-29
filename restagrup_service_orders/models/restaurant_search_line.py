# -*- coding: utf-8 -*-
from odoo import fields, models


class RestaurantSearchLine(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    partner_worked_with = fields.Boolean(
        related='partner_id.restaurant_worked_with', string='Ya trabajado con este',
    )
