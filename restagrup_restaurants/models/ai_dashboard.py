# -*- coding: utf-8 -*-
"""A4: tablero «Actividad IA». Se calcula al abrirlo; no guarda nada que haya que mantener."""
from datetime import timedelta

from odoo import api, fields, models

WINDOW_DAYS = 7
REVIEWED_STATES = ['confirmed', 'corrected', 'discarded']


class RestagrupAiDashboard(models.TransientModel):
    _name = 'restagrup.ai.dashboard'
    _description = 'Panel de actividad de la IA'

    mails_processed = fields.Integer(string='Correos procesados', compute='_compute_stats')
    reviewed_count = fields.Integer(string='Propuestas revisadas', compute='_compute_stats')
    confirmed_pct = fields.Float(string='Confirmadas sin corrección (%)', compute='_compute_stats', digits=(5, 1))
    pending_queue = fields.Integer(string='Correos pendientes de aprobar', compute='_compute_stats')
    errors_week = fields.Integer(string='Errores de la semana', compute='_compute_stats')

    def _compute_display_name(self):
        for board in self:
            board.display_name = 'Actividad IA'

    def _since(self):
        return fields.Datetime.now() - timedelta(days=WINDOW_DAYS)

    def _week_domain(self, *extra):
        return [('create_date', '>=', self._since()), *extra]

    @api.depends_context('uid')
    def _compute_stats(self):
        Log = self.env['restagrup.ai.log'].sudo()
        for board in self:
            week = board._week_domain
            # Cada correo deja una clasificación (si está activada) y, si es petición, una extracción: con la
            # clasificación activada la primera cubre todos los correos; apagada, solo hay extracciones.
            board.mails_processed = max(
                Log.search_count(week(('kind', '=', 'mail_classification'))),
                Log.search_count(week(('kind', '=', 'lead_extraction'))),
            )
            reviewed = Log.search_count(week(('state', 'in', REVIEWED_STATES)))
            confirmed = Log.search_count(week(('state', '=', 'confirmed')))
            board.reviewed_count = reviewed
            board.confirmed_pct = round(confirmed * 100.0 / reviewed, 1) if reviewed else 0.0
            board.errors_week = Log.search_count(week(('state', '=', 'error')))
            board.pending_queue = self.env['restagrup.pending.mail'].sudo().search_count([('state', '=', 'pending')])

    @api.model
    def open_dashboard(self):
        board = self.create({})
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': board.id,
            'view_mode': 'form', 'target': 'current', 'name': 'Actividad IA',
        }

    def _log_action(self, name, domain):
        return {
            'type': 'ir.actions.act_window', 'name': name, 'res_model': 'restagrup.ai.log',
            'view_mode': 'list,form', 'domain': domain,
        }

    def action_view_errors(self):
        return self._log_action('Errores de la IA', self._week_domain(('state', '=', 'error')))

    def action_view_reviewed(self):
        return self._log_action('Propuestas revisadas', self._week_domain(('state', 'in', REVIEWED_STATES)))

    def action_view_all(self):
        return self._log_action('Actividad de la IA', self._week_domain())

    def action_view_pending_mails(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Pendientes de aprobar', 'res_model': 'restagrup.pending.mail',
            'view_mode': 'list,form', 'domain': [('state', '=', 'pending')],
        }
