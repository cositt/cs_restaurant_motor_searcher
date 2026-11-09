# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Los expedientes terminados pasan a numerarse TER, como en el CRM de Restagrup (PET → PRE → EXP → TER).
    Las fases son noupdate: el dato se cambia aquí, y solo si nadie lo ha tocado a mano."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    stage = env.ref('restagrup_service_orders.stage_cerrado', raise_if_not_found=False)
    if stage and stage.restagrup_doc_prefix == 'EXP':
        stage.restagrup_doc_prefix = 'TER'
        _logger.info('Fase «%s»: prefijo de documento EXP → TER.', stage.name)
