# -*- coding: utf-8 -*-
"""Plantillas de los correos que genera el sistema: un texto editable por tipo y, por tipo, si sale solo."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')
BLANK_LINES_RE = re.compile(r'\n{3,}')
SPACES_RE = re.compile(r' {2,}')
# Textos que antes se editaban en Ajustes: pasan a su plantilla (con lo que antes se añadía solo detrás).
LEGACY_TEXTS = {
    'quote_reminder': ('restagrup.quote_reminder_text', '\n\n{firma}'),
    'agency_reminder': ('restagrup.agency_reminder_text', '\n\n{enlace}\n\n{firma}'),
}


class RestagrupMailTemplate(models.Model):
    _name = 'restagrup.mail.template'
    _description = 'Plantilla de correo'
    _order = 'sequence, id'

    code = fields.Char(string='Código', required=True, readonly=True, index=True)
    name = fields.Char(string='Correo', required=True, readonly=True)
    recipient = fields.Selection(
        [('restaurant', 'Restaurante'), ('agency', 'Agencia')], string='Para', readonly=True)
    note = fields.Text(string='Cuándo sale', readonly=True)
    sequence = fields.Integer(default=10)
    subject = fields.Char(string='Asunto', required=True)
    body = fields.Text(string='Texto', required=True)
    placeholders = fields.Char(
        string='Marcadores', readonly=True,
        help='Se sustituyen al preparar el correo. Un marcador que no esté en la lista se deja tal cual.')
    can_auto_send = fields.Boolean(
        string='Puede salir solo', readonly=True,
        help='Los correos que manda una persona con un botón no pasan por la cola: para ellos no hay envío automático.')
    auto_send = fields.Boolean(
        string='Enviar automáticamente',
        help='Marcado: sale solo, sin pasar por «Pendientes de aprobar». Desmarcado (por defecto): espera a que una'
             ' persona lo apruebe.')

    _code_unique = models.Constraint('unique(code)', 'Ya hay una plantilla para ese tipo de correo.')

    @api.constrains('auto_send', 'can_auto_send')
    def _check_auto_send(self):
        for template in self:
            if template.auto_send and not template.can_auto_send:
                raise ValidationError(_('«%s» lo manda una persona con un botón: no puede salir solo.') % template.name)

    @api.model
    def _get(self, code):
        return self.sudo().search([('code', '=', code)], limit=1)

    def _render(self, values):
        """(asunto, texto) con los marcadores sustituidos. Las líneas que quedan vacías no se acumulan."""
        self.ensure_one()

        def fill(text):
            return PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)

        body = '\n'.join(line.rstrip() for line in fill(self.body or '').splitlines())
        return SPACES_RE.sub(' ', fill(self.subject or '')).strip(), BLANK_LINES_RE.sub('\n\n', body).strip()

    @api.model
    def _compose(self, code, values, fallback):
        """(asunto, texto) con la plantilla del tipo; si alguien la borró, `fallback()` (el texto de siempre)."""
        template = self._get(code)
        return template._render(values) if template else fallback()

    @api.model
    def _import_legacy_texts(self):
        """Lleva a su plantilla el texto que se hubiera escrito en Ajustes y lo quita de allí. Se puede repetir."""
        params = self.env['ir.config_parameter'].sudo()
        for code, (key, tail) in LEGACY_TEXTS.items():
            text = (params.get_param(key) or '').strip()
            template = self._get(code)
            if not text or not template:
                continue
            template.body = text + tail
            params.set_param(key, False)
