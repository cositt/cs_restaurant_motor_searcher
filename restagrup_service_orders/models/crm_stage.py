# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    restagrup_stage_key = fields.Selection(
        [('peticion', 'Petición'), ('presupuesto', 'Presupuesto'), ('expediente', 'Expediente'), ('cerrado', 'Cerrado')],
        string='Fase del flujo de RestaGrup',
        help='Fase del documento del grupo en el flujo de RestaGrup. Las etapas sin fase no entran en el flujo.',
    )
    restagrup_doc_prefix = fields.Char(
        string='Prefijo del documento', help='Letras con las que empieza el número del documento en esta etapa.',
    )
