# -*- coding: utf-8 -*-
from odoo import fields, models


class RestagrupEventType(models.Model):
    _name = 'restagrup.event.type'
    _description = 'Tipo de servicio de un grupo (desayuno, comida, cena…)'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True, translate=True)
    sequence = fields.Integer(string='Orden', default=10)
    active = fields.Boolean(string='Activo', default=True)
    default_time = fields.Float(
        string='Hora de base',
        help='Hora que se pone al servicio si el correo no dice otra (comida 13:30, cena 21:00…). 0 = sin hora.')
