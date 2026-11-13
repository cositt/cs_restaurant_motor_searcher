# -*- coding: utf-8 -*-
"""Reunión 12/11 (8.2): los menús que ya existían sin año en el nombre pasan a llevar el de su temporada."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['restagrup.restaurant.menu']._restagrup_add_season_to_names()
