# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: lo que la IA rellena del correo de la agencia.

- Comensales: siempre el total. «48 personas + chófer y guía» son 50.
- Hora: si el correo no la dice, la de base por tipo de servicio (desayuno 9:00, comida 13:30, merienda 17:00,
  cena 21:00). Si la dice, la del correo.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestRonda0911Ai(TransactionCase):

    def _extract(self, response):
        lead = self.env['crm.lead'].create({'name': 'Ayuntamiento'})
        with patch(LLM, return_value=(response, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>48 personas + chófer y guía</p>'})
        return lead

    def _event(self, **event):
        base = {'ciudad': 'Sevilla', 'fecha': '2026-12-15', 'tipo': 'comida', 'pax': 48, 'notas': None}
        base.update(event)
        return self._extract({'eventos': [base]}).restagrup_event_ids

    # --- comensales totales ---

    def test_driver_and_guide_are_added_to_the_diners(self):
        event = self._event(acompanantes=2)
        self.assertEqual(event.pax, 50)

    def test_without_companions_the_count_stays(self):
        self.assertEqual(self._event().pax, 48)

    def test_lead_total_also_counts_the_companions(self):
        lead = self._extract({'num_pax': 48, 'eventos': [
            {'ciudad': 'Sevilla', 'fecha': '2026-12-15', 'tipo': 'comida', 'pax': 48, 'acompanantes': 2}]})
        self.assertEqual(lead.restagrup_event_ids.pax, 50)

    def test_the_prompt_asks_for_the_companions(self):
        from odoo.addons.restagrup_email_ai.models.crm_lead import EXTRACTION_SYSTEM_PROMPT
        self.assertIn('acompanantes', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('merienda', EXTRACTION_SYSTEM_PROMPT)

    # --- hora de base por tipo de servicio ---

    def test_lunch_without_hour_is_at_half_past_one(self):
        self.assertEqual(self._event(hora=None).event_time, 13.5)

    def test_default_hours_per_service(self):
        # Reunión 12/11 (6.7): el desayuno pasa a las 08:30.
        expected = {'desayuno': 8.5, 'comida': 13.5, 'merienda': 17.0, 'cena': 21.0}
        for key, hour in expected.items():
            with self.subTest(service=key):
                self.assertEqual(self._event(tipo=key, hora=None).event_time, hour)

    def test_the_hour_in_the_email_wins(self):
        self.assertEqual(self._event(hora='14:15').event_time, 14.25)

    def test_merienda_is_a_service_type(self):
        event = self._event(tipo='merienda')
        self.assertEqual(event.event_type_id, self.env.ref('restagrup_core.event_type_snack'))

    def test_choosing_the_type_by_hand_fills_the_hour(self):
        lead = self.env['crm.lead'].create({'name': 'A mano'})
        event = self.env['restagrup.lead.event'].new({
            'lead_id': lead.id, 'event_type_id': self.env.ref('restagrup_core.event_type_dinner').id})
        event._onchange_event_type_default_time()
        self.assertEqual(event.event_time, 21.0)

    def test_default_hour_is_marked_and_a_hand_written_one_is_not(self):
        event = self._event(hora=None)
        self.assertTrue(event.event_time_is_default)
        event.event_time = 14.0
        self.assertFalse(event.event_time_is_default)
        self.assertFalse(self._event(hora='14:00').event_time_is_default)
