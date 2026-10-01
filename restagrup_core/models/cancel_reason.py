# -*- coding: utf-8 -*-
from odoo import fields, models


class RestagrupCancelReason(models.Model):
    _name = 'restagrup.cancel.reason'
    _description = 'Motivo de cancelación o cambio de un restaurante'
    _order = 'sequence, id'

    name = fields.Char(string='Motivo', required=True, translate=True)
    sequence = fields.Integer(string='Orden', default=10)
    active = fields.Boolean(string='Activo', default=True)
