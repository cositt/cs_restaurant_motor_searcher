# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    restagrup_google_places_api_key = fields.Char(
        string='Google Places API Key',
        config_parameter='restagrup.google_places_api_key',
        help='Usada por el buscador de restaurantes para traer candidatos nuevos por ciudad.',
    )
    restagrup_llm_providers_order = fields.Char(
        string='Orden de proveedores IA',
        config_parameter='restagrup.llm_providers_order',
        default='groq,gemini',
        help='Separados por comas, p.ej. "groq,gemini". Se prueban en orden, el primero con'
             ' clave configurada que responda gana.',
    )
    restagrup_groq_api_key = fields.Char(
        string='Groq API Key', config_parameter='restagrup.groq_api_key',
    )
    restagrup_gemini_api_key = fields.Char(
        string='Gemini API Key', config_parameter='restagrup.gemini_api_key',
    )
    restagrup_quote_reminder_text = fields.Char(
        string='Texto del recordatorio de presupuesto',
        config_parameter='restagrup.quote_reminder_text',
        help='Mensaje que Odoo manda solo a un restaurante que no ha respondido a la'
             ' petición de presupuesto (una vez, a los 3 días). Vacío = texto por defecto.',
    )
    restagrup_agency_reminder_days = fields.Integer(
        string='Días antes del servicio para reclamar', config_parameter='restagrup.agency_reminder_days',
        default=14,
        help='Un presupuesto enviado a la agencia y sin respuesta genera un recordatorio cuando faltan estos'
             ' días o menos para el servicio.',
    )
    restagrup_agency_reminder_text = fields.Char(
        string='Texto del recordatorio a la agencia', config_parameter='restagrup.agency_reminder_text',
        help='Mensaje del recordatorio a la agencia (el enlace al presupuesto y la firma se añaden solos).'
             ' Vacío = texto por defecto.',
    )
    restagrup_change_confirm_pct = fields.Float(
        string='Cambio de comensales que pide confirmación (%)', config_parameter='restagrup.change_confirm_pct',
        default=20.0,
        help='Al reenviar cambios, un cambio de comensales por encima de este porcentaje (o cualquier cambio de'
             ' fecha u hora) devuelve la hoja del restaurante a «pendiente de confirmar». Por debajo solo informa.'
             ' Mínimo práctico: 1 (con 0 vuelve el valor por defecto).',
    )
    restagrup_classify_incoming = fields.Selection(
        [('enabled', 'Activada'), ('disabled', 'Desactivada')],
        string='Clasificación de correos entrantes', default='enabled',
        config_parameter='restagrup.classify_incoming',
        help='Activada: antes de crear un lead, la IA clasifica el correo; solo una petición nueva crea lead y'
             ' el resto va a «Correos por revisar» o se enlaza al grupo que corresponda. Si la IA falla o duda,'
             ' se crea el lead como siempre.',
    )
    restagrup_system_sender = fields.Char(
        string='Remitente de los envíos del sistema', config_parameter='restagrup.system_sender',
        help='Dirección desde la que salen los correos que genera el sistema (recordatorios, peticiones de datos,'
             ' avisos): la cuenta dedicada. Vacío = el correo del usuario. Debe poder enviar con tu servidor'
             ' de correo saliente.',
    )
    restagrup_alert_user_id = fields.Many2one(
        'res.users', string='Usuario de alertas IA', config_parameter='restagrup.alert_user_id',
        help='Quien recibe una actividad cuando la IA falla o detecta una incidencia y el grupo no tiene un'
             ' responsable asignado.',
    )
    restagrup_send_mode = fields.Selection(
        [('approval', 'Con aprobación'), ('automatic', 'Automático')],
        string='Modo de envíos automáticos', default='approval',
        config_parameter='restagrup.send_mode',
        help='Con aprobación (por defecto): los correos que genera el sistema (p. ej. el recordatorio a'
             ' restaurantes) quedan en Restagrup > Pendientes de aprobar y no salen hasta que una persona'
             ' los aprueba. Automático: salen solos. Los envíos que dispara una persona con un botón'
             ' no pasan por la cola.',
    )
    restagrup_default_margin_percent = fields.Float(
        string='Margen por defecto (%)', default=20.0,
        help='Lo que Restagrup añade al precio del restaurante (por defecto 20 %). Se aplica'
             ' solo al crear el presupuesto de venta: precio al cliente = precio del restaurante'
             ' × (1 + margen/100). La hoja de servicio del restaurante lleva su propio precio.'
             ' El equipo puede ajustar el precio a mano en la línea antes de enviarla.',
    )

    def get_values(self):
        res = super().get_values()
        res['restagrup_default_margin_percent'] = self.env['restagrup.pricing'].margin_percent()
        return res

    def set_values(self):
        super().set_values()
        # Se guarda a mano: con config_parameter Odoo borra el parámetro cuando vale 0 y volvería
        # a aplicarse el 20 % por defecto, así que nadie podría poner "sin margen".
        self.env['ir.config_parameter'].sudo().set_param(
            'restagrup.default_margin_percent', repr(float(self.restagrup_default_margin_percent)),
        )
