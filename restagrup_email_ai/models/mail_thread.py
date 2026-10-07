# -*- coding: utf-8 -*-
"""A5: clasificación con IA del correo entrante antes de crear un lead."""
import logging

from odoo import _, api, models
from odoo.tools import email_normalize, html2plaintext

_logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM_PROMPT = """\
Eres un asistente que clasifica los correos que llegan al buzón central de un restaurante-broker de
grupos (agencias de viaje, restaurantes y proveedores), en español o en inglés.
Devuelve SOLO un objeto JSON, sin texto adicional, con estas claves exactas:
"categoria": uno de
  "new_request" (petición nueva de presupuesto para un grupo que aún no existe),
  "group_change" (la agencia cambia algo de un grupo ya pedido: fecha, comensales, menú, cancelación),
  "agency_reply" (respuesta de una agencia a un presupuesto o propuesta ya enviados),
  "invoice" (factura, albarán, cobro o pago),
  "incident" (queja, retraso, restaurante sin reserva, cancelación urgente o cualquier problema grave),
  "other" (publicidad, spam, consultas generales u otra cosa);
"resumen": una frase en español con lo esencial del correo.
Si dudas entre petición nueva y otra cosa, elige "new_request"."""

CATEGORIES = ('new_request', 'group_change', 'agency_reply', 'invoice', 'incident', 'other')
LINKABLE = ('group_change', 'agency_reply')
INBOX_MODEL = 'restagrup.inbox.mail'
MAX_TEXT_CHARS = 4000


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def _message_route_process(self, message, message_dict, routes):
        return super()._message_route_process(message, message_dict, self._restagrup_classify_routes(message_dict, routes))

    @api.model
    def _restagrup_classify_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param('restagrup.classify_incoming') != 'disabled'

    @api.model
    def _restagrup_classify_routes(self, message_dict, routes):
        """Solo toca las rutas que crearían un lead nuevo. Las respuestas a un hilo existente y el resto de
        modelos (líneas de búsqueda, hojas de servicio…) siguen su camino. Un correo se clasifica una vez."""
        creates_lead = [r for r in routes or () if r[0] == 'crm.lead' and not r[1]]
        if not creates_lead or not self._restagrup_classify_enabled():
            return routes
        category, summary, log = self._restagrup_classify(message_dict)
        if category in (None, 'new_request'):
            return routes
        new_routes = []
        for route in routes:
            if route not in creates_lead:
                new_routes.append(route)
                continue
            target = self._restagrup_match_existing(category, message_dict) if category in LINKABLE else None
            if target:
                new_routes.append((target[0], target[1], None, route[3], route[4]))
            else:
                log.state = 'pending'  # lo revisa una persona desde la bandeja
                if category != 'incident':  # una incidencia ya tiene su propia alerta urgente
                    log._notify_safely(False, None)
                new_routes.append((INBOX_MODEL, False, {
                    'category': category, 'summary': summary, 'ai_log_id': log.id}, route[3], route[4]))
        return new_routes

    @api.model
    def _restagrup_classify(self, message_dict):
        """(categoría, resumen, registro de la IA), o (None, None, registro) si no se puede clasificar: ante la
        duda no se desvía nada y el correo crea el lead como siempre."""
        raw_body = message_dict.get('body') or ''
        text = '%s\n\n%s' % (message_dict.get('subject') or '', html2plaintext(raw_body).strip() if raw_body else '')
        label = '%s — %s' % (message_dict.get('subject') or _('(sin asunto)'), message_dict.get('email_from') or '')
        data, _provider, log = self.env['restagrup.llm.connector'].run(
            'mail_classification', CLASSIFY_SYSTEM_PROMPT, text.strip()[:MAX_TEXT_CHARS], label=label, review=False)
        category = data.get('categoria') if isinstance(data, dict) else None
        if category not in CATEGORIES:
            if data is not None:
                _logger.info('Clasificación de correo desconocida %r: se crea el lead.', category)
            return None, None, log
        return category, (data.get('resumen') or '')[:500] or False, log

    @api.model
    def _restagrup_match_existing(self, category, message_dict):
        """(modelo, id) del lead existente al que corresponde un cambio o una respuesta, o None. Solo se enlaza
        sin ambigüedad: un único lead abierto del remitente, o el que se nombra en el asunto o el texto."""
        email = email_normalize(message_dict.get('email_from') or '')
        if not email:
            return None
        leads = self.env['crm.lead'].sudo().search([
            '|', ('email_normalized', '=', email), ('partner_id.email_normalized', '=', email),
            ('stage_id.is_won', '=', False),
        ], order='id desc')
        if len(leads) == 1:
            return 'crm.lead', leads.id
        haystack = ('%s %s' % (message_dict.get('subject') or '', html2plaintext(message_dict.get('body') or ''))).lower()
        named = leads.filtered(lambda lead: lead.name and lead.name.lower() in haystack)
        return ('crm.lead', named.id) if len(named) == 1 else None
