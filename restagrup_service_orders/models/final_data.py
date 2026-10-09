# -*- coding: utf-8 -*-
"""Datos definitivos de cada evento (menú, intolerancias, guía, comensales) y aviso interno cuando se acerca la fecha."""
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

FINAL_DATA_DAYS_PARAM = 'restagrup.final_data_days'
DEFAULT_FINAL_DATA_DAYS = 7
REMINDER_SUMMARY = 'Datos pendientes antes del servicio'


class RestagrupLeadEventFinalData(models.Model):
    _inherit = 'restagrup.lead.event'

    guide_contact = fields.Char(string='Contacto del guía')
    intolerances = fields.Text(string='Intolerancias / alergias')
    no_intolerances = fields.Boolean(
        string='Sin intolerancias', help='La agencia ha confirmado que no hay intolerancias ni alergias.')
    pax_final = fields.Boolean(
        string='Comensales definitivos', help='El número de comensales ya es el definitivo.')
    final_missing = fields.Char(string='Datos por cerrar', compute='_compute_final_missing')

    @api.depends(
        'guide_contact', 'intolerances', 'no_intolerances', 'pax_final', 'search_ids.chosen_line_id.menu_id',
        'search_ids.sale_order_id.order_line.restaurant_id',
    )
    def _compute_final_missing(self):
        for event in self:
            missing = []
            menu_defined = event.search_ids.chosen_line_id.menu_id or any(
                line.restaurant_id for line in event.search_ids.sale_order_id.order_line)
            if not menu_defined:
                missing.append(_('Menú definitivo'))
            if not (event.intolerances or event.no_intolerances):
                missing.append(_('Intolerancias'))
            if not event.guide_contact:
                missing.append(_('Contacto del guía'))
            if not event.pax_final:
                missing.append(_('Comensales definitivos'))
            event.final_missing = ', '.join(missing)

    @api.model
    def _final_data_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(FINAL_DATA_DAYS_PARAM)
        try:
            return int(raw) if raw else DEFAULT_FINAL_DATA_DAYS
        except ValueError:
            return DEFAULT_FINAL_DATA_DAYS

    @api.model
    def _cron_final_data_reminders(self):
        """Cron diario: avisa internamente (actividad + aviso) de los eventos de un expediente que se acercan y aún
        tienen datos por cerrar. No escribe a nadie de fuera: solo avisa al responsable. Una vez por grupo mientras
        el aviso siga abierto."""
        today = fields.Date.context_today(self)
        events = self.search([
            ('event_date', '>=', today), ('event_date', '<=', today + timedelta(days=self._final_data_days())),
            ('lead_id.stage_id.restagrup_stage_key', '=', 'expediente'),
        ]).filtered('final_missing')
        for lead in events.lead_id:
            already = self.env['mail.activity'].sudo().search_count([
                ('res_model', '=', 'crm.lead'), ('res_id', '=', lead.id), ('summary', '=', REMINDER_SUMMARY)])
            if already:
                continue
            lines = ['%s: %s' % (event.display_name, event.final_missing)
                     for event in events.filtered(lambda e: e.lead_id == lead)]
            try:
                with self.env.cr.savepoint():
                    self.env['restagrup.ai.log']._notify(lead, REMINDER_SUMMARY, '<br/>'.join(lines), source=lead)
            except Exception:  # noqa: BLE001 -- un grupo roto no debe parar al resto
                _logger.exception('Aviso de datos pendientes fallido para %s', lead.name)
