# -*- coding: utf-8 -*-
"""Lo que la IA saca del correo de la agencia (PPT de Conchita 2026-11-04, diapositivas 1 y 2):
el título de la petición es la referencia del grupo y la agencia queda enlazada (o creada con los datos de la
firma) con quien escribe como contacto suyo."""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
SIGNATURE = {
    'nombre': 'Erika Zarandona', 'telefono': '+34 600 111 222', 'direccion': 'Calle Larios 5',
    'codigo_postal': '29005', 'ciudad': 'Málaga', 'web': 'www.clandestina-viajes.es',
}


@tagged('post_install', '-at_install')
class TestGroupAndAgency(TransactionCase):

    def _extract(self, data, email_from='Erika Zarandona <erika@clandestina-viajes.es>'):
        lead = self.env['crm.lead'].create({'name': 'Fwd: petición grupo', 'email_from': email_from})
        response = dict({'eventos': [], 'agencia': None, 'firma': None, 'referencia_grupo': None,
                         'tipo_grupo': None}, **data)
        with patch(LLM, return_value=(response, 'groq')):
            lead._restagrup_extract_from_email({'body': '<p>Petición de grupo</p>', 'email_from': email_from})
        return lead

    # --- 1.2 título = referencia del grupo ---

    def test_title_is_the_group_name(self):
        lead = self._extract({'referencia_grupo': 'Colegio Teresianas', 'tipo_grupo': 'escolar'})
        self.assertEqual(lead.name, 'Colegio Teresianas')

    def test_without_group_name_the_title_is_the_kind_of_group(self):
        self.assertEqual(self._extract({'tipo_grupo': 'escolar'}).name, 'Grupo escolar')
        self.assertEqual(self._extract({'tipo_grupo': 'deportivo'}).name, 'Grupo deportivo')

    def test_default_title_is_adult_group(self):
        self.assertEqual(self._extract({}).name, 'Grupo adulto')
        self.assertEqual(self._extract({'tipo_grupo': 'corporativo'}).name, 'Grupo adulto')

    def test_prompt_asks_for_group_reference_and_signature(self):
        from odoo.addons.restagrup_email_ai.models.crm_lead import EXTRACTION_SYSTEM_PROMPT
        self.assertIn('"referencia_grupo"', EXTRACTION_SYSTEM_PROMPT)
        self.assertIn('"firma"', EXTRACTION_SYSTEM_PROMPT)

    # --- 2.1 agencia y contacto ---

    def test_new_agency_is_created_with_the_signature_data(self):
        lead = self._extract({'agencia': 'Agencia Clandestina', 'firma': SIGNATURE})
        contact = lead.partner_id
        self.assertEqual(contact.name, 'Erika Zarandona')
        self.assertEqual(contact.email, 'erika@clandestina-viajes.es')
        agency = contact.parent_id
        self.assertEqual(agency.name, 'Agencia Clandestina')
        self.assertTrue(agency.is_company)
        self.assertEqual((agency.phone, agency.street, agency.zip, agency.city),
                         ('+34 600 111 222', 'Calle Larios 5', '29005', 'Málaga'))
        self.assertIn('clandestina-viajes.es', agency.website)

    def test_street_keeps_only_street_and_number(self):
        """La IA a veces copia la línea entera de la dirección: el código postal y la ciudad van en sus campos."""
        signature = dict(SIGNATURE, direccion='Calle Larios 5, 29005 Málaga')
        agency = self._extract({'agencia': 'Agencia Clandestina', 'firma': signature}).partner_id.parent_id
        self.assertEqual((agency.street, agency.zip, agency.city), ('Calle Larios 5', '29005', 'Málaga'))

    def test_existing_agency_is_reused_and_not_overwritten(self):
        agency = self.env['res.partner'].create({
            'name': 'Agencia Clandestina', 'is_company': True, 'phone': '+34 952 000 000'})
        lead = self._extract({'agencia': 'agencia clandestina', 'firma': SIGNATURE})
        self.assertEqual(lead.partner_id.parent_id, agency)
        self.assertEqual(agency.phone, '+34 952 000 000', 'lo que ya tenía la ficha manda')
        self.assertEqual(agency.street, 'Calle Larios 5', 'lo que faltaba se completa con la firma')

    def test_new_agent_of_a_known_agency_is_added_as_contact(self):
        agency = self.env['res.partner'].create({
            'name': 'Clandestina Viajes S.L.', 'is_company': True, 'email': 'reservas@clandestina-viajes.es'})
        lead = self._extract({'agencia': 'Agencia Clandestina', 'firma': SIGNATURE})
        self.assertEqual(lead.partner_id.parent_id, agency, 'mismo dominio de correo: es la misma agencia')
        self.assertEqual(self.env['res.partner'].search_count([('name', '=', 'Agencia Clandestina')]), 0)

    def test_generic_mail_domains_do_not_match_agencies(self):
        other = self.env['res.partner'].create({
            'name': 'Otra Agencia', 'is_company': True, 'email': 'otra@gmail.com'})
        lead = self._extract({'agencia': 'Viajes Sol', 'firma': SIGNATURE}, email_from='Ana <ana.sol@gmail.com>')
        self.assertNotEqual(lead.partner_id.parent_id, other)
        self.assertEqual(lead.partner_id.parent_id.name, 'Viajes Sol')

    def test_known_contact_keeps_its_agency(self):
        agency = self.env['res.partner'].create({'name': 'Agencia Uno', 'is_company': True})
        contact = self.env['res.partner'].create({
            'name': 'Erika', 'email': 'erika@clandestina-viajes.es', 'parent_id': agency.id})
        lead = self._extract({'agencia': 'Agencia Clandestina', 'firma': SIGNATURE})
        self.assertEqual(lead.partner_id, contact)
        self.assertEqual(contact.parent_id, agency)

    def test_private_person_gets_a_contact_without_agency(self):
        lead = self._extract({'firma': {'nombre': 'Luis Pérez'}}, email_from='luis@gmail.com')
        self.assertEqual(lead.partner_id.name, 'Luis Pérez')
        self.assertFalse(lead.partner_id.parent_id)

    def test_restaurants_are_never_taken_as_the_contact(self):
        if 'is_restaurant' not in self.env['res.partner']._fields:
            self.skipTest('Sin el módulo de restaurantes')
        restaurant = self.env['res.partner'].create({
            'name': 'Mesón', 'email': 'erika@clandestina-viajes.es', 'is_restaurant': True})
        lead = self._extract({'agencia': 'Agencia Clandestina', 'firma': SIGNATURE})
        self.assertNotEqual(lead.partner_id, restaurant)
