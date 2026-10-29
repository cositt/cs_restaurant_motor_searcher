# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """La llegada prevista de las hojas ya creadas pasa a UTC (antes se guardaba la hora local y salía 1 h tarde)."""
    env = api.Environment(cr, SUPERUSER_ID, {'tz': 'Europe/Madrid'})
    fixed = env['purchase.order.line']._restagrup_fix_naive_planned_dates()
    _logger.info('Hojas de servicio: %s llegadas previstas pasadas a UTC.', fixed)
