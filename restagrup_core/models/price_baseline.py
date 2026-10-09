# -*- coding: utf-8 -*-
from odoo import api, fields, models

AUDIENCE_SELECTION = [('adults', 'Adultos'), ('students', 'Estudiantes'), ('athletes', 'Deportistas')]
WEEKEND_WEEKDAYS = (5, 6)


class RestagrupPriceBaseline(models.Model):
    """Baremo orientativo por persona para cuando la agencia no indica presupuesto.
    Solo es una estimación de partida: nunca fija el precio y el equipo la puede cambiar."""
    _name = 'restagrup.price.baseline'
    _description = 'Baremo orientativo de precio por persona'
    _order = 'event_type_id, audience, day_type, city, id'

    name = fields.Char(string='Descripción', required=True)
    active = fields.Boolean(string='Activo', default=True)
    event_type_id = fields.Many2one(
        'restagrup.event.type', string='Tipo de evento', required=True, ondelete='cascade')
    audience = fields.Selection(AUDIENCE_SELECTION, string='Público', required=True, default='adults')
    day_type = fields.Selection(
        [('any', 'Cualquier día'), ('weekday', 'Entre semana'), ('weekend', 'Fin de semana')],
        string='Día', required=True, default='any')
    city = fields.Char(
        string='Ciudad', help='Vacío = vale para cualquier ciudad. Una ciudad concreta tiene preferencia.')
    price_pp = fields.Float(string='Precio por persona (€, IVA incl.)', digits=(16, 2), required=True)

    @api.model
    def estimate(self, event_type, event_date, city=None, audience='adults'):
        """Precio por persona orientativo, o 0.0 si no hay baremo aplicable (nunca bloquea)."""
        if not event_type:
            return 0.0
        is_weekend = bool(event_date) and event_date.weekday() in WEEKEND_WEEKDAYS
        wanted_city = (city or '').strip().casefold()
        best_score, best_price = -1, 0.0
        for baseline in self.search([
            ('event_type_id', '=', event_type.id), ('audience', '=', audience or 'adults'),
        ]):
            baseline_city = (baseline.city or '').strip().casefold()
            if baseline_city and baseline_city != wanted_city:
                continue
            if baseline.day_type == 'weekend' and not is_weekend:
                continue
            if baseline.day_type == 'weekday' and (is_weekend or not event_date):
                continue
            score = (2 if baseline_city else 0) + (1 if baseline.day_type != 'any' else 0)
            if score > best_score:
                best_score, best_price = score, baseline.price_pp
        return best_price
