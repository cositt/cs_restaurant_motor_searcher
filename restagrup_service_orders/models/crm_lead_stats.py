# -*- coding: utf-8 -*-
"""Estadísticas que pide Conchita (notas 05/11 y respuesta 09/11): tiempos y media de cambios, por comercial,
por destino y por agencia.

- Tiempo hasta el presupuesto: desde que entra la petición hasta que el grupo pasa a Presupuesto (al enviar la
  propuesta a la agencia o al pasarlo a mano).
- Tiempo hasta el expediente: desde que entra la petición hasta que la agencia confirma (pasa a Expediente).
- Tiempo hasta el cierre: desde que entra la petición hasta que se cierra el expediente.
- Cambios: presupuestos y proformas reenviados a la agencia después del primero de cada uno.
Cuenta la primera vez que se entra en cada fase: volver atrás y adelante no la reinicia.
"""
from odoo import api, fields, models
from odoo.tools import SQL

SECONDS_PER_HOUR = 3600.0
HOURS_FIELDS = ('restagrup_hours_to_quote', 'restagrup_hours_to_file', 'restagrup_hours_to_close')
STAGE_DATE_FIELDS = {
    'presupuesto': 'restagrup_quote_date', 'expediente': 'restagrup_file_date', 'cerrado': 'restagrup_close_date',
}


def _hours_between(start, end):
    """Horas entre dos fechas; 0 si falta alguna (la media no cuenta esos ceros, ver `_read_group_select`)."""
    return (end - start).total_seconds() / SECONDS_PER_HOUR if start and end else 0.0


class CrmLeadStats(models.Model):
    _inherit = 'crm.lead'

    restagrup_quote_date = fields.Datetime(string='Pasó a presupuesto', copy=False, readonly=True)
    restagrup_file_date = fields.Datetime(string='Pasó a expediente', copy=False, readonly=True)
    restagrup_close_date = fields.Datetime(string='Se cerró el expediente', copy=False, readonly=True)
    restagrup_hours_to_quote = fields.Float(
        string='Horas hasta el presupuesto', compute='_compute_restagrup_hours', store=True, aggregator='avg',
        digits=(16, 1), help='Desde que entra la petición hasta que pasa a Presupuesto.')
    restagrup_hours_to_file = fields.Float(
        string='Horas hasta el expediente', compute='_compute_restagrup_hours', store=True, aggregator='avg',
        digits=(16, 1), help='Desde que entra la petición hasta que la agencia confirma.')
    restagrup_hours_to_close = fields.Float(
        string='Horas hasta el cierre', compute='_compute_restagrup_hours', store=True, aggregator='avg',
        digits=(16, 1), help='Desde que entra la petición hasta que se cierra el expediente. Depende mucho de la '
                             'antelación con la que se pide la reserva.')
    restagrup_proposals_sent = fields.Integer(
        string='Propuestas enviadas', copy=False, readonly=True, aggregator='sum')
    restagrup_proformas_sent = fields.Integer(
        string='Proformas enviadas', copy=False, readonly=True, aggregator='sum')
    restagrup_quote_changes = fields.Integer(
        string='Cambios', compute='_compute_restagrup_quote_changes', store=True, aggregator='avg',
        help='Presupuestos y proformas reenviados a la agencia después del primero de cada uno.')
    restagrup_destination = fields.Char(
        string='Destino', compute='_compute_restagrup_destination', store=True,
        help='Población del primer servicio.')
    restagrup_agency_id = fields.Many2one(
        'res.partner', string='Agencia', related='partner_id.commercial_partner_id', store=True)

    @api.depends('create_date', 'restagrup_quote_date', 'restagrup_file_date', 'restagrup_close_date')
    def _compute_restagrup_hours(self):
        for lead in self:
            lead.restagrup_hours_to_quote = _hours_between(lead.create_date, lead.restagrup_quote_date)
            lead.restagrup_hours_to_file = _hours_between(lead.create_date, lead.restagrup_file_date)
            lead.restagrup_hours_to_close = _hours_between(lead.create_date, lead.restagrup_close_date)

    @api.depends('restagrup_proposals_sent', 'restagrup_proformas_sent')
    def _compute_restagrup_quote_changes(self):
        for lead in self:
            lead.restagrup_quote_changes = (
                max(lead.restagrup_proposals_sent - 1, 0) + max(lead.restagrup_proformas_sent - 1, 0))

    @api.depends('restagrup_event_ids.city', 'restagrup_event_ids.event_date', 'restagrup_city')
    def _compute_restagrup_destination(self):
        for lead in self:
            lead.restagrup_destination = lead.restagrup_first_service_city or False

    def _read_group_select(self, aggregate_spec, query):
        """Media de horas solo de los grupos que han llegado a esa fase: un grupo sin terminar (0 h) no la baja."""
        fname, _sep, func = aggregate_spec.partition(':')
        if func == 'avg' and fname in HOURS_FIELDS:
            self.check_field_access_rights('read', [fname])
            return SQL('AVG(NULLIF(%s, 0))', self._field_to_sql(self._table, fname, query))
        return super()._read_group_select(aggregate_spec, query)

    def _restagrup_note_proposal_sent(self):
        for lead in self:
            lead.restagrup_proposals_sent += 1

    def _restagrup_note_proforma_sent(self):
        for lead in self:
            lead.restagrup_proformas_sent += 1

    def write(self, vals):
        result = super().write(vals)
        if 'stage_id' in vals:
            self._restagrup_stamp_stage_dates()
        return result

    def _restagrup_stamp_stage_dates(self):
        now = fields.Datetime.now()
        for lead in self:
            field = STAGE_DATE_FIELDS.get(lead.restagrup_stage_key)
            if field and not lead[field]:
                lead[field] = now
            # Pasar directo a expediente también cuenta como presupuesto hecho.
            if lead.restagrup_stage_key in ('expediente', 'cerrado') and not lead.restagrup_quote_date:
                lead.restagrup_quote_date = lead.restagrup_file_date or now
            if lead.restagrup_stage_key == 'cerrado' and not lead.restagrup_file_date:
                lead.restagrup_file_date = lead.restagrup_close_date or now
