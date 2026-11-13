# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestHallazgosGuia1311Agency(TransactionCase):
    """Hallazgo (2) al capturar la guía en prod (13/11): si el correo nombra otra agencia, la empresa del lead sigue
    siendo la de quien escribe, y el aviso se quita al cambiar el cliente o al darlo por revisado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sol = cls.env['res.partner'].create({'name': 'Sol y Nubes', 'is_company': True})
        cls.ana = cls.env['res.partner'].create({
            'name': 'Ana Sol', 'email': 'ana@solynubes.example', 'parent_id': cls.sol.id})
        cls.peregrino = cls.env['res.partner'].create({'name': 'Peregrino Travel', 'is_company': True})

    def _mismatch_lead(self, **vals):
        lead = self.env['crm.lead'].create(dict({'name': 'Grupo guía', 'email_from': 'ana@solynubes.example'}, **vals))
        with patch(LLM, return_value=({'agencia': 'Peregrino Travel', 'eventos': []}, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>Petición</p>'})
        self.assertTrue(lead.restagrup_agency_warning)
        return lead

    def test_company_name_stays_the_senders_agency(self):
        self.assertEqual(self._mismatch_lead().partner_name, 'Sol y Nubes')

    def test_company_name_stays_when_the_contact_was_already_set(self):
        # Como en prod: el correo entra y Odoo ya enlaza a quien escribe antes de que lea la IA.
        self.assertEqual(self._mismatch_lead(partner_id=self.ana.id).partner_name, 'Sol y Nubes')

    def test_changing_the_customer_clears_the_warning(self):
        lead = self._mismatch_lead()
        lead.partner_id = self.peregrino
        self.assertFalse(lead.restagrup_agency_warning)

    def test_dismiss_button_clears_the_warning(self):
        lead = self._mismatch_lead()
        lead.action_dismiss_agency_warning()
        self.assertFalse(lead.restagrup_agency_warning)
        self.assertEqual(lead.partner_id, self.ana)

    def test_dismiss_button_is_in_the_form(self):
        arch = self.env['crm.lead'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('action_dismiss_agency_warning', arch)
