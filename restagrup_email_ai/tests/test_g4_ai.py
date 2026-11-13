# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestG4Ai(TransactionCase):
    """Reunión 12/11, bloque G4: 3.2 un grupo escolar se estima con el baremo de estudiantes; 2.1 si el correo
    nombra una agencia distinta de la de quien escribe, se avisa en vez de asignar a ciegas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lunch = cls.env.ref('restagrup_core.event_type_lunch')
        Baseline = cls.env['restagrup.price.baseline']
        Baseline.search([('event_type_id', '=', lunch.id)]).unlink()
        Baseline.create({'name': 'G4 adults', 'event_type_id': lunch.id, 'audience': 'adults', 'day_type': 'any', 'price_pp': 16.0})
        Baseline.create({'name': 'G4 students', 'event_type_id': lunch.id, 'audience': 'students', 'day_type': 'any', 'price_pp': 14.5})
        Baseline.create({'name': 'G4 athletes', 'event_type_id': lunch.id, 'audience': 'athletes', 'day_type': 'any', 'price_pp': 15.0})
        cls.sol = cls.env['res.partner'].create({'name': 'Sol y Nubes', 'is_company': True})
        cls.ana = cls.env['res.partner'].create({
            'name': 'Ana Sol', 'email': 'ana@solynubes.example', 'parent_id': cls.sol.id})

    def _extract(self, response, email_from='otro@agencia.example'):
        lead = self.env['crm.lead'].create({'name': 'Grupo G4', 'email_from': email_from})
        with patch(LLM, return_value=(response, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>Petición</p>'})
        return lead

    def _event(self, group_type):
        return {'tipo_grupo': group_type, 'eventos': [
            {'ciudad': 'Madrid', 'fecha': '2026-12-11', 'tipo': 'comida', 'pax': 42}]}

    # --- 3.2 ---
    def test_school_group_services_are_for_students(self):
        event = self._extract(self._event('escolar')).restagrup_event_ids
        self.assertEqual(event.audience, 'students')
        self.assertEqual(event.budget_pp, 14.5)
        self.assertTrue(event.budget_is_estimate)

    def test_sports_group_services_are_for_athletes(self):
        event = self._extract(self._event('deportivo')).restagrup_event_ids
        self.assertEqual(event.audience, 'athletes')
        self.assertEqual(event.budget_pp, 15.0)

    def test_adult_group_keeps_the_adult_baseline(self):
        event = self._extract(self._event(None)).restagrup_event_ids
        self.assertEqual(event.audience, 'adults')
        self.assertEqual(event.budget_pp, 16.0)

    # --- 2.1 ---
    def test_named_agency_different_from_the_senders_warns(self):
        lead = self._extract({'agencia': 'Peregrino Travel', 'eventos': []}, email_from='ana@solynubes.example')
        self.assertEqual(lead.partner_id, self.ana)
        self.assertEqual(self.ana.parent_id, self.sol, 'no se cambia la agencia de quien escribe')
        self.assertIn('Peregrino Travel', lead.restagrup_agency_warning)
        self.assertIn('Sol y Nubes', lead.restagrup_agency_warning)
        self.assertTrue(any('Peregrino Travel' in (m.body or '') for m in lead.message_ids))

    def test_same_agency_written_differently_does_not_warn(self):
        lead = self._extract({'agencia': 'SOL Y NUBES S.L.', 'eventos': []}, email_from='ana@solynubes.example')
        self.assertFalse(lead.restagrup_agency_warning)

    def test_new_sender_gets_the_named_agency_without_warning(self):
        lead = self._extract({'agencia': 'Peregrino Travel', 'eventos': []}, email_from='luis@peregrino.example')
        self.assertEqual(lead.partner_id.parent_id.name, 'Peregrino Travel')
        self.assertFalse(lead.restagrup_agency_warning)

    def test_warning_is_shown_in_the_form(self):
        arch = self.env['crm.lead'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('restagrup_agency_warning', arch)
