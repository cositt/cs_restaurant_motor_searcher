# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Primera entrada en cualquiera de estas fases = fecha de esa marca.
STAGE_MARKS = {
    'restagrup_quote_date': ('presupuesto', 'expediente', 'cerrado'),
    'restagrup_file_date': ('expediente', 'cerrado'),
}


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
    """Estadísticas (notas de Conchita 05/11): rellena las fechas de paso a presupuesto y a expediente de los
    grupos que ya existían, con el historial de cambios de fase. Lo que no tenga historial se queda sin fecha."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Lead = env['crm.lead'].with_context(active_test=False)
    for field, keys in STAGE_MARKS.items():
        stages = env['crm.stage'].search([('restagrup_stage_key', 'in', keys)])
        entries = _first_entries(cr, stages.ids)
        leads = Lead.browse(list(entries)).exists().filtered(lambda lead: not lead[field])
        for lead in leads:
            lead[field] = entries[lead.id]
        _logger.info('Estadísticas: %s rellenada en %s grupos.', field, len(leads))
