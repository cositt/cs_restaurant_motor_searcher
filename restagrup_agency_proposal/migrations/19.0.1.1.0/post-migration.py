# -*- coding: utf-8 -*-
"""Plazo de cambios de comensales: de 48 h laborables a 72 h (respuesta de Conchita 2026-11-09)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['restagrup.payment.settings']._restagrup_upgrade_final_pax_hours()
