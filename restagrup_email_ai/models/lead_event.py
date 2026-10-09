# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.restagrup_core.models.price_baseline import AUDIENCE_SELECTION

ESTIMATE_TRIGGERS = ('event_type_id', 'event_date', 'city', 'audience')


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
    audience = fields.Selection(AUDIENCE_SELECTION, string='Público', default='adults')
    budget_pp = fields.Float(
        string='Precio/persona (€)', digits=(16, 2),
        help='Presupuesto por persona. Si la agencia no lo indica se rellena con el baremo orientativo'
             ' (marcado como estimado); se puede cambiar libremente.',
    )
    budget_is_estimate = fields.Boolean(
        string='Estimado', copy=False,
        help='El precio viene del baremo orientativo y no de la agencia.',
    )
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

    def _estimate_values(self):
        """Valores de precio por persona según el baremo; vacío (0, no estimado) si no hay baremo."""
        self.ensure_one()
        price = self.env['restagrup.price.baseline'].estimate(
            self.event_type_id, self.event_date, city=self.city, audience=self.audience)
        return {'budget_pp': price, 'budget_is_estimate': bool(price)}

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        for event, vals in zip(events, vals_list):
            if not vals.get('budget_pp'):
                super(RestagrupLeadEvent, event).write(event._estimate_values())
            else:
                super(RestagrupLeadEvent, event).write({'budget_is_estimate': False})
        return events

    def write(self, vals):
        if 'budget_pp' in vals:
            if vals['budget_pp']:
                vals = {**vals, 'budget_is_estimate': False}
                return super().write(vals)
            result = super().write({k: v for k, v in vals.items() if k != 'budget_pp'}) if len(vals) > 1 else True
            for event in self:
                super(RestagrupLeadEvent, event).write(event._estimate_values())
            return result
        result = super().write(vals)
        if any(key in vals for key in ESTIMATE_TRIGGERS):
            for event in self.filtered(lambda e: e.budget_is_estimate or not e.budget_pp):
                super(RestagrupLeadEvent, event).write(event._estimate_values())
        return result
