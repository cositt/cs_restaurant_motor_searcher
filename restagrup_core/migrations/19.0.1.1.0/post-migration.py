# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: hora de base por tipo de servicio (los tipos son noupdate, se rellena una vez)."""
from odoo import SUPERUSER_ID, api

DEFAULT_TIMES = {
    'restagrup_core.event_type_breakfast': 9.0,
    'restagrup_core.event_type_lunch': 13.5,
    'restagrup_core.event_type_dinner': 21.0,
    'restagrup_core.event_type_snack': 17.0,
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, hour in DEFAULT_TIMES.items():
        event_type = env.ref(xmlid, raise_if_not_found=False)
        if event_type and not event_type.default_time:
            event_type.default_time = hour
