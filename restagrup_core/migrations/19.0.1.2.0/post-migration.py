# -*- coding: utf-8 -*-
"""Reunión 12/11 (6.7): el desayuno de base pasa de 09:00 a 08:30. Los tipos son noupdate: se cambia aquí, y solo si
nadie lo había tocado (sigue a las 09:00)."""
from odoo import SUPERUSER_ID, api

OLD_BREAKFAST, NEW_BREAKFAST = 9.0, 8.5


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    breakfast = env.ref('restagrup_core.event_type_breakfast', raise_if_not_found=False)
    if breakfast and breakfast.default_time == OLD_BREAKFAST:
        breakfast.default_time = NEW_BREAKFAST
