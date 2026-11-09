# -*- coding: utf-8 -*-
"""Estadísticas (respuesta de Conchita 2026-11-09): rellena la fecha de cierre del expediente de los grupos que ya
existían, con el historial de cambios de fase. Destino y agencia se calculan solos al crear los campos."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _first_entries(cr, stage_ids):
    """{lead_id: fecha} de la primera vez que cada grupo entró en una de esas fases, según el historial."""
    cr.execute("""
        SELECT m.res_id, MIN(m.date)
          FROM mail_tracking_value t
          JOIN mail_message m ON m.id = t.mail_message_id
          JOIN ir_model_fields f ON f.id = t.field_id
         WHERE m.model = 'crm.lead' AND f.model = 'crm.lead' AND f.name = 'stage_id'
           AND t.new_value_integer = ANY(%s)
         GROUP BY m.res_id
    """, [list(stage_ids)])
    return dict(cr.fetchall())


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    stages = env['crm.stage'].search([('restagrup_stage_key', '=', 'cerrado')])
    entries = _first_entries(cr, stages.ids)
    leads = env['crm.lead'].with_context(active_test=False).browse(list(entries)).exists().filtered(
        lambda lead: not lead.restagrup_close_date)
    for lead in leads:
        lead.restagrup_close_date = entries[lead.id]
    _logger.info('Estadísticas: restagrup_close_date rellenada en %s grupos.', len(leads))
