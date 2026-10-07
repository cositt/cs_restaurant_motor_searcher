# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
GEMINI_URL_TMPL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'


class RestagrupLlmConnector(models.AbstractModel):
    _name = 'restagrup.llm.connector'
    _description = 'Conector LLM con fallback de proveedores (Restagrup)'

    def _get_param(self, key, default=False):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    def extract_json(self, system_prompt, user_content):
        """Pide al LLM configurado (con fallback entre proveedores, mismo patrón
        que motor-restaurantes) una respuesta JSON. Nunca lanza -- si todo falla
        devuelve (None, None), y quien llama decide cómo marcarlo para revisión
        humana (nunca se inventa un dato ni se actúa solo)."""
        order = [
            p.strip() for p in
            (self._get_param('restagrup.llm_providers_order') or 'groq,gemini').split(',')
            if p.strip()
        ]
        for provider in order:
            caller = getattr(self, f'_call_{provider}', None)
            if not caller:
                continue
            try:
                result = caller(system_prompt, user_content)
            except Exception:
                _logger.exception('Fallo llamando a LLM provider=%s', provider)
                continue
            if result is not None:
                return result, provider
        return None, None

    def run(self, kind, system_prompt, user_content, source=None, label=False, review=True):
        """extract_json + registro de la actividad (A4). Devuelve (datos, proveedor, registro). `review` dice si
        luego una persona confirma o corrige el resultado; si no, el registro queda como automático."""
        data, provider = self.extract_json(system_prompt, user_content)
        log = self.env['restagrup.ai.log']._record(
            kind, user_content, data, provider, source=source, label=label, review=review)
        return data, provider, log

    def _call_groq(self, system_prompt, user_content):
        api_key = self._get_param('restagrup.groq_api_key')
        if not api_key:
            return None
        model = self._get_param('restagrup.groq_model') or 'openai/gpt-oss-120b'
        response = requests.post(
            GROQ_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_content},
                ],
                'response_format': {'type': 'json_object'},
                'temperature': 0,
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        return json.loads(content)

    def _call_gemini(self, system_prompt, user_content):
        api_key = self._get_param('restagrup.gemini_api_key')
        if not api_key:
            return None
        model = self._get_param('restagrup.gemini_model') or 'gemini-3.6-flash'
        response = requests.post(
            GEMINI_URL_TMPL.format(model=model),
            params={'key': api_key},
            json={
                'contents': [{'parts': [{'text': f'{system_prompt}\n\n{user_content}'}]}],
                'generationConfig': {'response_mime_type': 'application/json'},
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(content)
