# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestG2Defaults(TransactionCase):
    """Reunión 12/11, bloque G2: 6.7 desayuno a las 08:30, 6.8 si la agencia no dice nada, grupo adulto y servicio
    de comida, 6.3 sin pestaña «Datos IA»."""

    def _extract(self, response):
        lead = self.env['crm.lead'].create({'name': 'Grupo G2'})
        with patch(LLM, return_value=(response, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>Somos 30 en Sevilla el 15/12</p>'})
        return lead

    def test_breakfast_default_hour_is_half_past_eight(self):
        self.assertEqual(self.env.ref('restagrup_core.event_type_breakfast').default_time, 8.5)

    def test_service_without_type_is_lunch_at_half_past_one(self):
        lead = self._extract({'eventos': [{'ciudad': 'Sevilla', 'fecha': '2026-12-15', 'tipo': None, 'pax': 30}]})
        event = lead.restagrup_event_ids
        self.assertEqual(event.event_type_id, self.env.ref('restagrup_core.event_type_lunch'))
        self.assertEqual(event.event_time, 13.5)
        self.assertTrue(event.event_time_is_default)
        self.assertEqual(event.audience, 'adults')

    def test_group_without_type_is_adult(self):
        lead = self._extract({'eventos': [{'ciudad': 'Sevilla', 'fecha': '2026-12-15', 'pax': 30}]})
        self.assertEqual(lead.restagrup_group_type, 'adulto')

    def test_group_type_given_by_the_agency_is_kept(self):
        lead = self._extract({'tipo_grupo': 'escolar', 'eventos': [
            {'ciudad': 'Sevilla', 'fecha': '2026-12-15', 'tipo': 'cena', 'pax': 30}]})
        self.assertEqual(lead.restagrup_group_type, 'escolar')
        self.assertEqual(lead.restagrup_event_ids.event_type_id, self.env.ref('restagrup_core.event_type_dinner'))

    def test_lead_form_has_no_ai_data_tab(self):
        arch = self.env['crm.lead'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertNotIn('name="restagrup_ai"', arch)
        self.assertNotIn('string="Datos IA"', arch)
