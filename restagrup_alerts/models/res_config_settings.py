# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    restagrup_alerts_notify_owner = fields.Boolean(
        string='Avisar también al comercial', config_parameter='restagrup.alerts_notify_owner',
        help='Cada comercial ve los avisos de sus propias peticiones aunque no esté suscrito a ese tipo.',
    )
