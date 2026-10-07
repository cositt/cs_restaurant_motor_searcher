# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
Eres un asistente que lee peticiones de grupos (comidas, cenas, desayunos...) que agencias de
viaje envían a un restaurante-broker, en español o en inglés. Hoy es {hoy}.
Devuelve SOLO un objeto JSON, sin texto adicional, con estas claves exactas:
"eventos": lista con UN objeto por cada servicio pedido (cada comida, cena, desayuno... en cada
ciudad y fecha). Cada objeto tiene: "ciudad" (string o null), "fecha" (string YYYY-MM-DD o
null), "tipo" (uno de: desayuno, aperitivo, comida, cena, coffee_break, otro; o null si el
texto no lo dice), "pax" (entero o null) y "notas" (string corto con requisitos como alergias
o presupuesto por persona, o null). Si una fecha no indica el año, usa la próxima vez que
ocurra a partir de hoy. Si no se pide ningún servicio, "eventos" es una lista vacía.
Además: "ciudad" (string o null), "num_pax" (entero o null) y "fecha_servicio" (string
YYYY-MM-DD o null) del primer evento, y "tipo_grupo" (string corto:
corporativo/escolar/familiar/otro, o null).
Si un dato no aparece claramente en el texto, pon null -- nunca lo inventes."""

MAX_EVENTS = 20
EVENT_TYPE_XMLIDS = {
    'desayuno': 'restagrup_core.event_type_breakfast',
    'aperitivo': 'restagrup_core.event_type_aperitif',
    'comida': 'restagrup_core.event_type_lunch',
    'cena': 'restagrup_core.event_type_dinner',
    'coffee_break': 'restagrup_core.event_type_coffee_break',
    'otro': 'restagrup_core.event_type_other',
}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_city = fields.Char(string='Ciudad (IA)')
    restagrup_pax = fields.Integer(string='Nº comensales (IA)')
    restagrup_service_date = fields.Date(string='Fecha de servicio (IA)')
    restagrup_group_type = fields.Char(string='Tipo de grupo (IA)')
    restagrup_extraction_state = fields.Selection(
        selection=[
            ('pending', 'Pendiente'),
            ('done', 'Extraído'),
            ('error', 'Error'),
            ('no_data', 'Sin datos suficientes'),
        ],
        string='Extracción IA', copy=False,
        help='La extracción es siempre un borrador para que un humano lo revise antes de'
             ' convertir el lead en presupuesto -- nunca se crea nada automáticamente.',
    )
    restagrup_extraction_provider = fields.Char(string='Proveedor IA usado', copy=False)
    restagrup_event_ids = fields.One2many(
        'restagrup.lead.event', 'lead_id', string='Eventos',
        help='Cada comida, cena, etc. que pide el grupo, en su ciudad y fecha. La IA los propone como'
             ' borrador a partir del email; una persona los revisa.',
    )

    def message_new(self, msg_dict, custom_values=None):
        lead = super().message_new(msg_dict, custom_values=custom_values)
        lead._restagrup_extract_from_email(msg_dict)
        return lead

    def _restagrup_extract_from_email(self, msg_dict):
        self.ensure_one()
        raw_body = msg_dict.get('body') or ''
        text = html2plaintext(raw_body).strip() if raw_body else ''
        if not text:
            self.restagrup_extraction_state = 'no_data'
            return

        connector = self.env['restagrup.llm.connector']
        system_prompt = EXTRACTION_SYSTEM_PROMPT.replace('{hoy}', fields.Date.context_today(self).isoformat())
        data, provider, _log = connector.run('lead_extraction', system_prompt, text, source=self, label=self.name)

        if data is None:
            self.write({'restagrup_extraction_state': 'error'})
            self.message_post(body=_(
                'No se pudo extraer datos automáticamente del email (LLM no configurado o'
                ' sin respuesta) -- revisar y rellenar a mano.'
            ))
            return

        event_vals = self._restagrup_event_vals_list(data)
        first = event_vals[0] if event_vals else {}
        self.write({
            'restagrup_city': (data.get('ciudad') or first.get('city') or '') or False,
            'restagrup_pax': self._restagrup_safe_int(data.get('num_pax') or first.get('pax')),
            'restagrup_service_date': (
                self._restagrup_safe_date(data.get('fecha_servicio')) or first.get('event_date') or False
            ),
            'restagrup_group_type': (data.get('tipo_grupo') or '') or False,
            'restagrup_extraction_state': 'done',
            'restagrup_extraction_provider': provider,
        })
        if event_vals:
            self.env['restagrup.lead.event'].create([dict(vals, lead_id=self.id) for vals in event_vals])
        self.message_post(body=_(
            'Datos extraídos automáticamente por IA (%(provider)s) -- revisar antes de'
            ' convertir en presupuesto.'
        ) % {'provider': provider})

    def _restagrup_event_vals_list(self, data):
        """Eventos que propone la IA, como borradores. Si la IA contesta al estilo antiguo (sin lista
        de eventos), se construye uno con los campos sueltos. Nunca lanza: un dato sucio se deja vacío."""
        events = data.get('eventos')
        if not isinstance(events, list) or not events:
            legacy = {
                'ciudad': data.get('ciudad'), 'fecha': data.get('fecha_servicio'),
                'pax': data.get('num_pax'), 'tipo': None, 'notas': None,
            }
            events = [legacy] if any(legacy[key] for key in ('ciudad', 'fecha', 'pax')) else []
        vals_list = []
        for event in events:
            if not isinstance(event, dict):
                continue
            vals_list.append({
                'sequence': 10 * (len(vals_list) + 1),
                'city': (event.get('ciudad') or '') or False,
                'event_date': self._restagrup_safe_date(event.get('fecha')),
                'event_type_id': self._restagrup_event_type_id(event.get('tipo')),
                'pax': self._restagrup_safe_int(event.get('pax')),
                'notes': (event.get('notas') or '') or False,
                'state': 'draft',
            })
        return vals_list[:MAX_EVENTS]

    def _restagrup_event_type_id(self, key):
        """Clave del prompt (comida, cena…) -> tipo de evento. Sin clave: vacío (no se inventa);
        clave desconocida: 'Otro'."""
        if not key or not isinstance(key, str):
            return False
        xmlid = EVENT_TYPE_XMLIDS.get(key.strip().lower(), EVENT_TYPE_XMLIDS['otro'])
        return self.env.ref(xmlid, raise_if_not_found=False).id or False

    @staticmethod
    def _restagrup_safe_date(value):
        try:
            return fields.Date.to_date(value) or False
        except (ValueError, TypeError, OverflowError):
            return False

    @staticmethod
    def _restagrup_safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
