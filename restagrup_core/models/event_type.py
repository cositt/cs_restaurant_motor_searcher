# -*- coding: utf-8 -*-
from odoo import fields, models


class RestagrupEventType(models.Model):
    _name = 'restagrup.event.type'
    _description = 'Tipo de evento de un grupo (desayuno, comida, cena…)'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True, translate=True)
    sequence = fields.Integer(string='Orden', default=10)
    active = fields.Boolean(string='Activo', default=True)
