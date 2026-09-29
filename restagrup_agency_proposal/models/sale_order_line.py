# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    restagrup_include_in_proposal = fields.Boolean(
        string='Incluir en propuesta', default=True,
        help='Desmarcar para que este restaurante/línea no salga en el PDF de propuesta'
             ' que se manda a la agencia (p.ej. si se descarta antes de confirmar).',
    )
