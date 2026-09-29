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
    restagrup_default_margin_percent = fields.Float(
        string='Margen por defecto (%)', config_parameter='restagrup.default_margin_percent',
        help='Se aplica automáticamente sobre el presupuesto del restaurante al crear'
             ' el presupuesto de venta (precio venta = presupuesto × (1 + margen/100)).'
             ' El equipo sigue pudiendo ajustar el precio a mano en la línea antes de enviarla.',
    )
