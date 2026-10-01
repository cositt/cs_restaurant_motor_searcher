# -*- coding: utf-8 -*-
from odoo import fields, models


class RestagrupNoticeTemplate(models.Model):
    _name = 'restagrup.notice.template'
    _description = 'Plantilla de aviso a restaurantes'
    _order = 'sequence, id'

    name = fields.Char(string='Nombre', required=True)
    subject = fields.Char(string='Asunto', required=True)
    body = fields.Html(string='Texto', required=True)
    sequence = fields.Integer(string='Orden', default=10)
    active = fields.Boolean(string='Activa', default=True)
