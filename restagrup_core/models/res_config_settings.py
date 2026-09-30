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
    restagrup_default_margin_percent = fields.Float(
        string='Margen por defecto (%)', config_parameter='restagrup.default_margin_percent',
        default=20.0,
        help='Lo que Restagrup añade al precio del restaurante (por defecto 20 %). Se aplica'
             ' solo al crear el presupuesto de venta: precio al cliente = precio del restaurante'
             ' × (1 + margen/100). La hoja de servicio del restaurante lleva su propio precio.'
             ' El equipo puede ajustar el precio a mano en la línea antes de enviarla.',
    )
