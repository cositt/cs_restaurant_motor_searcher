# -*- coding: utf-8 -*-
"""A4: registro de la actividad de la IA -- qué hizo, con qué origen, qué propuso y cómo terminó."""
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

EXCERPT_CHARS = 800

KINDS = [
    ('lead_extraction', 'Extracción de datos del lead'),
    ('quote_extraction', 'Importe de un presupuesto'),
    ('data_extraction', 'Datos de la ficha de un restaurante'),
    ('mail_classification', 'Clasificación de un correo'),
    ('sheet_classification', 'Respuesta a una hoja de servicio'),
]
STATES = [
    ('pending', 'Pendiente de revisar'),
    ('confirmed', 'Confirmado'),
    ('corrected', 'Corregido'),
    ('discarded', 'Descartado'),
    ('auto', 'Automático (sin revisión)'),
    ('error', 'Error'),
]
# Dónde buscar al responsable a partir del origen. Primero lo más específico: en una hoja de servicio `user_id`
# es quien la creó (el comprador), no el responsable del grupo, que es el del presupuesto de origen.
RESPONSIBLE_PATHS = ('restagrup_sale_order_id.user_id', 'search_id.user_id', 'user_id')
MODEL_PARAMS = {'groq': ('restagrup.groq_model', 'openai/gpt-oss-120b'),
                'gemini': ('restagrup.gemini_model', 'gemini-3.6-flash')}


class RestagrupAiLog(models.Model):
    _name = 'restagrup.ai.log'
    _description = 'Actividad de la IA'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Acción', compute='_compute_name')
    kind = fields.Selection(KINDS, string='Tipo', required=True, index=True)
    state = fields.Selection(STATES, string='Estado', default='pending', required=True, index=True)
    provider = fields.Char(string='Proveedor')
    model_name = fields.Char(string='Modelo')
    source_model = fields.Char(string='Modelo de origen')
    source_res_id = fields.Integer(string='Registro de origen')
    source_label = fields.Char(string='Origen')
    input_excerpt = fields.Text(string='Texto leído')
    output = fields.Text(string='Propuesta de la IA')
    error_message = fields.Char(string='Error')
    reviewed_by = fields.Many2one('res.users', string='Revisado por', readonly=True)
    reviewed_date = fields.Datetime(string='Revisado el', readonly=True)

    @api.depends('kind', 'source_label')
    def _compute_name(self):
        labels = dict(KINDS)
        for log in self:
            log.name = '%s — %s' % (labels.get(log.kind, ''), log.source_label) if log.source_label else labels.get(log.kind, '')

    # --- registro ---

    @api.model
    def _record(self, kind, text, data, provider, source=None, label=False, review=True):
        """Anota una acción de la IA. Siempre con sudo: quien la dispara puede ser cualquier usuario (o el
        servidor de correo) y el registro no es suyo. Un fallo (data None) queda como error y avisa."""
        failed = data is None
        vals = {
            'kind': kind,
            'state': 'error' if failed else ('pending' if review else 'auto'),
            'provider': provider or False,
            'model_name': self._model_name(provider),
            'source_model': source._name if source else False,
            'source_res_id': source.id if source else False,
            'source_label': label or (source.display_name if source else False),
            'input_excerpt': (text or '')[:EXCERPT_CHARS],
            'output': json.dumps(data, ensure_ascii=False, indent=1) if data is not None else False,
            'error_message': _('Sin respuesta de la IA (proveedor caído, sin clave o respuesta inválida).') if failed else False,
        }
        log = self.sudo().with_context(mail_create_nolog=True).create(vals)
        log._notify_safely(failed, source)
        return log

    def _notify_safely(self, failed, source):
        """Los avisos (actividad y aviso emergente) nunca deben impedir que se registre lo que entra: si algo
        falla al avisar, se anota y el registro se queda."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                if failed:
                    self._alert(_('La IA falló: %s') % (self.name or ''), self.error_message, source)
                else:
                    self._notify_review()
        except Exception:  # noqa: BLE001
            _logger.exception('No se pudo avisar de la actividad de la IA (registro %s)', self.id)

    @api.model
    def _model_name(self, provider):
        param, default = MODEL_PARAMS.get(provider, (False, False))
        if not param:
            return False
        return self.env['ir.config_parameter'].sudo().get_param(param) or default

    # --- alertas ---

    @api.model
    def _responsible_for(self, source=None):
        """Quien debe enterarse: el responsable del origen, o si no hay, el usuario de alertas de Ajustes."""
        if source:
            for path in RESPONSIBLE_PATHS:
                try:
                    user = source.sudo().mapped(path)
                except (KeyError, ValueError, AttributeError):
                    continue
                if user:
                    return user[:1]
        alert_id = self.env['ir.config_parameter'].sudo().get_param('restagrup.alert_user_id')
        return self.env['res.users'].sudo().browse(int(alert_id)).exists() if alert_id and alert_id.isdigit() else self.env['res.users']

    @api.model
    def _notify(self, target, summary, note=False, source=None):
        """Actividad pendiente en `target` (contador del reloj) y aviso emergente para el responsable del origen
        (o el usuario de alertas). Sin nadie a quien avisar, no se hace nada."""
        user = self._responsible_for(source)
        if not user:
            return False
        target.sudo().activity_schedule(
            'mail.mail_activity_data_todo', summary=summary, note=note or '', user_id=user.id,
        )
        self._toast(user, summary, note, sticky=True, kind='warning')
        return True

    @api.model
    def _toast(self, user, title, message=False, sticky=True, kind='info'):
        """Aviso emergente en tiempo real. Nunca debe romper lo que lo dispara (un correo entrando, una respuesta):
        si el bus falla, se anota y se sigue."""
        try:
            self.env['bus.bus'].sudo()._sendone(user.partner_id, 'simple_notification', {
                'title': title, 'message': message or '', 'sticky': sticky, 'type': kind,
            })
        except Exception:  # noqa: BLE001
            _logger.exception('No se pudo enviar el aviso emergente a %s', user.display_name)

    def _review_text(self):
        """(resumen, nota) del aviso de este registro, en el idioma del equipo."""
        self.ensure_one()
        data = json.loads(self.output) if self.output else {}
        label = self.source_label or ''
        if self.kind == 'quote_extraction':
            amount = data.get('importe')
            return (_('Presupuesto de %(name)s: %(amount)s € (por confirmar)') % {'name': label, 'amount': amount}
                    if amount else _('Respuesta de %s: revisa el presupuesto') % label), data.get('notas')
        if self.kind == 'data_extraction':
            return _('Datos de ficha propuestos para %s') % label, False
        if self.kind == 'mail_classification':
            return _('Correo por revisar: %s') % label, data.get('resumen')
        if self.kind == 'sheet_classification':
            states = {'accepted': _('aceptado'), 'rejected': _('rechazado'), 'needs_info': _('falta información'),
                      'serious_issue': _('incidencia grave'), 'unclear': _('no está claro')}
            return (_('%(name)s respondió a la hoja de servicio: %(state)s') % {
                'name': label, 'state': states.get(data.get('estado'), _('sin clasificar'))}), data.get('resumen')
        city = data.get('ciudad')
        return _('Grupo nuevo por revisar: %s') % label, (_('Ciudad: %(city)s · Comensales: %(pax)s') % {
            'city': city, 'pax': data.get('num_pax') or '?'} if city else False)

    def _notify_review(self):
        """Avisa de que hay algo de la IA que mirar. Pendiente de revisión: actividad (que desaparece al revisarlo)
        y aviso emergente. Informativo sin revisión (respuesta de una hoja de servicio): solo el aviso emergente.
        El resto de lo automático (un correo ya enlazado, una petición nueva) no hace ruido."""
        for log in self:
            if log.state != 'pending' and log.kind != 'sheet_classification':
                continue
            source = self.env[log.source_model].sudo().browse(log.source_res_id).exists() if log.source_model else None
            user = self._responsible_for(source)
            if not user:
                continue
            summary, note = log._review_text()
            if log.state == 'pending':
                log.sudo().activity_schedule(
                    'mail.mail_activity_data_todo', summary=summary, note=note or '', user_id=user.id)
            self._toast(user, summary, note, sticky=log.state == 'pending')

    def _alert(self, summary, note, source=None):
        self.ensure_one()
        return self._notify(self, summary, note, source)

    # --- cierre ---

    @api.model
    def _pending(self, kind, source):
        """Último registro pendiente de revisión de ese tipo y origen."""
        if not source or not source.id:
            return self.browse()
        return self.sudo().search([
            ('kind', '=', kind), ('state', '=', 'pending'),
            ('source_model', '=', source._name), ('source_res_id', '=', source.id),
        ], order='id desc', limit=1)

    @api.model
    def _resolve(self, kind, source, state):
        """Cierra el último registro pendiente de ese tipo y origen con el resultado de la revisión humana."""
        log = self._pending(kind, source)
        log._close(state)
        return log

    def _close(self, state):
        """Cierra los registros que sigan pendientes con el resultado de la revisión humana."""
        pending = self.sudo().filtered(lambda log: log.state == 'pending')
        pending.write({'state': state, 'reviewed_by': self.env.user.id, 'reviewed_date': fields.Datetime.now()})
        pending.activity_ids.unlink()  # la actividad de «revisar» ya no hace falta

    def action_open_source(self):
        self.ensure_one()
        if not (self.source_model and self.source_res_id):
            return False
        return {
            'type': 'ir.actions.act_window', 'res_model': self.source_model,
            'res_id': self.source_res_id, 'view_mode': 'form', 'target': 'current',
        }
