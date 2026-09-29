# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    restagrup_sale_line_id = fields.Many2one(
        'sale.order.line', string='Línea de presupuesto origen',
        readonly=True, copy=False, index=True,
    )
