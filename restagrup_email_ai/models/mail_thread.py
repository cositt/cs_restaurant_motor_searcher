# -*- coding: utf-8 -*-
"""A5: clasificación con IA del correo entrante antes de crear un lead."""
import json
import logging
import unicodedata

from odoo import _, api, fields, models
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
"resumen": una frase en español con lo esencial del correo;
"ciudad": la ciudad de la que habla el correo (string o null), "fecha": la fecha del servicio de la que
habla, en formato YYYY-MM-DD (string o null; si no indica el año, la próxima vez que ocurra a partir de {hoy}),
"num_pax": el número de comensales que menciona (entero o null). No inventes: si no aparece, null.
Si dudas entre petición nueva y otra cosa, elige "new_request"."""

MATCH_SYSTEM_PROMPT = """\
Eres un asistente que decide a cuál de los grupos candidatos de un cliente se refiere un correo (un cambio
o una respuesta). Recibirás el correo y la lista de candidatos con su id, nombre y servicios (ciudad, fecha
y comensales). Devuelve SOLO un objeto JSON con la clave "lead_id": el id del candidato al que se refiere el
correo, o null si no puedes saberlo con seguridad. Elige solo entre los ids de la lista; nunca inventes."""

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
        category, summary, log, hints = self._restagrup_classify(message_dict)
        if category in (None, 'new_request'):
            return routes
        new_routes = []
        for route in routes:
            if route not in creates_lead:
                new_routes.append(route)
                continue
            target = self._restagrup_match_existing(category, message_dict, hints) if category in LINKABLE else None
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
        """(categoría, resumen, registro de la IA, pistas), o (None, None, registro, {}) si no se puede clasificar: ante la
        duda no se desvía nada y el correo crea el lead como siempre."""
        raw_body = message_dict.get('body') or ''
        text = '%s\n\n%s' % (message_dict.get('subject') or '', html2plaintext(raw_body).strip() if raw_body else '')
        label = '%s — %s' % (message_dict.get('subject') or _('(sin asunto)'), message_dict.get('email_from') or '')
        prompt = CLASSIFY_SYSTEM_PROMPT.replace('{hoy}', fields.Date.context_today(self).isoformat())
        data, _provider, log = self.env['restagrup.llm.connector'].run(
            'mail_classification', prompt, text.strip()[:MAX_TEXT_CHARS], label=label, review=False)
        category = data.get('categoria') if isinstance(data, dict) else None
        if category not in CATEGORIES:
            if data is not None:
                _logger.info('Clasificación de correo desconocida %r: se crea el lead.', category)
            return None, None, log, {}
        return category, (data.get('resumen') or '')[:500] or False, log, self._restagrup_clean_hints(data)

    @api.model
    def _restagrup_clean_hints(self, data):
        """Ciudad, fecha y comensales que la IA vio en el correo; lo que no cuadre se descarta."""
        hints = {}
        city = data.get('ciudad')
        if isinstance(city, str) and city.strip():
            hints['ciudad'] = city.strip()
        try:
            day = fields.Date.to_date(data.get('fecha')) if data.get('fecha') else False
        except (ValueError, TypeError, OverflowError):
            day = False
        if day:
            hints['fecha'] = day
        return hints

    @staticmethod
    def _restagrup_norm(text):
        """Minúsculas y sin acentos, para comparar ciudades («MÁLAGA» = «malaga»)."""
        decomposed = unicodedata.normalize('NFKD', text or '')
        return ''.join(ch for ch in decomposed if not unicodedata.combining(ch)).strip().lower()

    @api.model
    def _restagrup_lead_places_and_days(self, lead):
        """Ciudades y fechas de un grupo: las de sus eventos y las del propio lead."""
        cities = {self._restagrup_norm(c) for c in lead.restagrup_event_ids.mapped('city') + [lead.restagrup_city] if c}
        days = {d for d in lead.restagrup_event_ids.mapped('event_date') + [lead.restagrup_service_date] if d}
        return cities, days

    @api.model
    def _restagrup_match_by_hints(self, leads, hints):
        """El candidato cuya ciudad y fecha coinciden con las del correo: 2 puntos por la ciudad y 2 por la
        fecha. Gana el que tenga más puntos, si es uno solo y al menos tiene uno de los dos datos."""
        city = self._restagrup_norm(hints.get('ciudad'))
        day = hints.get('fecha')
        if not (city or day):
            return None
        scores = {}
        for lead in leads:
            cities, days = self._restagrup_lead_places_and_days(lead)
            scores[lead.id] = (2 if city and city in cities else 0) + (2 if day and day in days else 0)
        best = max(scores.values(), default=0)
        winners = [lead_id for lead_id, score in scores.items() if score == best]
        return winners[0] if best >= 2 and len(winners) == 1 else None

    @api.model
    def _restagrup_match_by_ai(self, leads, message_dict):
        """Último desempate: la IA elige entre los grupos candidatos del propio remitente (y solo esos). Si no
        sabe, o contesta algo que no es un candidato, no se enlaza."""
        description = []
        for lead in leads:
            events = [{'ciudad': e.city, 'fecha': e.event_date and e.event_date.isoformat(), 'comensales': e.pax}
                      for e in lead.restagrup_event_ids]
            description.append({'id': lead.id, 'nombre': lead.name, 'servicios': events})
        raw_body = message_dict.get('body') or ''
        text = 'CORREO:\n%s\n%s\n\nCANDIDATOS:\n%s' % (
            message_dict.get('subject') or '', html2plaintext(raw_body).strip() if raw_body else '',
            json.dumps(description, ensure_ascii=False))
        data, _provider, _log = self.env['restagrup.llm.connector'].run(
            'lead_matching', MATCH_SYSTEM_PROMPT, text[:MAX_TEXT_CHARS], review=False,
            label=message_dict.get('subject') or _('(sin asunto)'))
        picked = data.get('lead_id') if isinstance(data, dict) else None
        return picked if picked in leads.ids else None

    @api.model
    def _restagrup_match_existing(self, category, message_dict, hints=None):
        """(modelo, id) del lead existente al que corresponde un cambio o una respuesta, o None. Se prueba, por
        orden: el único lead abierto del remitente, el que se nombra en el asunto o el texto, el que coincide en
        ciudad y fecha y, si sigue habiendo empate, el que elige la IA entre los candidatos."""
        email = email_normalize(message_dict.get('email_from') or '')
        if not email:
            return None
        leads = self.env['crm.lead'].sudo().search([
            '|', ('email_normalized', '=', email), ('partner_id.email_normalized', '=', email),
            ('stage_id.is_won', '=', False),
        ], order='id desc')
        if not leads:
            return None
        if len(leads) == 1:
            return 'crm.lead', leads.id
        haystack = ('%s %s' % (message_dict.get('subject') or '', html2plaintext(message_dict.get('body') or ''))).lower()
        named = leads.filtered(lambda lead: lead.name and lead.name.lower() in haystack)
        if len(named) == 1:
            return 'crm.lead', named.id
        picked = self._restagrup_match_by_hints(leads, hints or {}) or self._restagrup_match_by_ai(leads, message_dict)
        return ('crm.lead', picked) if picked else None
