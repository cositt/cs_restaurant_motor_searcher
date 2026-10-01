# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RestagrupLeadEvent(models.Model):
    _name = 'restagrup.lead.event'
    _description = 'Evento de un grupo (una comida, una cena… en una ciudad y una fecha)'
    _order = 'event_date, sequence, id'

    lead_id = fields.Many2one(
        'crm.lead', string='Grupo / Cliente', required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Orden', default=10)
    city = fields.Char(string='Ciudad')
    event_date = fields.Date(string='Fecha')
    event_type_id = fields.Many2one('restagrup.event.type', string='Tipo', ondelete='restrict')
    pax = fields.Integer(string='Comensales')
    notes = fields.Text(string='Notas')
    state = fields.Selection(
        selection=[('draft', 'Borrador'), ('searching', 'Con búsqueda')],
        string='Estado', default='draft', required=True, copy=False,
        help='Borrador: lo propuso la IA o se escribió a mano y aún no se han buscado restaurantes.',
    )
    display_name = fields.Char(compute='_compute_display_name', string='Evento')

    @api.depends('city', 'event_date', 'event_type_id', 'pax')
    def _compute_display_name(self):
        for event in self:
            parts = [
                event.event_type_id.name,
                event.city,
                event.event_date and event.event_date.strftime('%d/%m'),
                event.pax and '%s pax' % event.pax,
            ]
            event.display_name = ' · '.join(part for part in parts if part) or 'Evento'
