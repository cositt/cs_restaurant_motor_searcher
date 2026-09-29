# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
Eres un asistente que lee peticiones de grupos (comidas/cenas) que agencias de viaje envían
a un restaurante-broker. Devuelve SOLO un objeto JSON, sin texto adicional, con estas claves
exactas: "ciudad" (string o null), "num_pax" (entero o null), "fecha_servicio" (string en
formato YYYY-MM-DD, la primera fecha de servicio mencionada, o null), "tipo_grupo" (string
corto: corporativo/escolar/familiar/otro, o null).
Si un dato no aparece claramente en el texto, pon null -- nunca lo inventes."""


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
        data, provider = connector.extract_json(EXTRACTION_SYSTEM_PROMPT, text)

        if data is None:
            self.write({'restagrup_extraction_state': 'error'})
            self.message_post(body=_(
                'No se pudo extraer datos automáticamente del email (LLM no configurado o'
                ' sin respuesta) -- revisar y rellenar a mano.'
            ))
            return

        self.write({
            'restagrup_city': (data.get('ciudad') or '') or False,
            'restagrup_pax': self._restagrup_safe_int(data.get('num_pax')),
            'restagrup_service_date': fields.Date.to_date(data.get('fecha_servicio')),
            'restagrup_group_type': (data.get('tipo_grupo') or '') or False,
            'restagrup_extraction_state': 'done',
            'restagrup_extraction_provider': provider,
        })
        self.message_post(body=_(
            'Datos extraídos automáticamente por IA (%(provider)s) -- revisar antes de'
            ' convertir en presupuesto.'
        ) % {'provider': provider})

    @staticmethod
    def _restagrup_safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
