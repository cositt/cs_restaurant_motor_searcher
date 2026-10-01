# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """El antiguo "Comida/Cena" (service_meal) pasa al tipo de evento nuevo. La columna vieja se
    conserva: no se borran datos."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['sale.order.line']._restagrup_fill_event_type_from_meal()
