# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'

THREE_EVENTS = {
    'ciudad': 'Málaga', 'num_pax': 42, 'fecha_servicio': '2026-11-15', 'tipo_grupo': 'corporativo',
    'eventos': [
        {'ciudad': 'Málaga', 'fecha': '2026-11-15', 'tipo': 'comida', 'pax': 42, 'notas': 'Sin gluten'},
        {'ciudad': 'Málaga', 'fecha': '2026-11-15', 'tipo': 'cena', 'pax': 42, 'notas': None},
        {'ciudad': 'Sevilla', 'fecha': '2026-11-16', 'tipo': 'cena', 'pax': 40, 'notas': None},
    ],
}


@tagged('post_install', '-at_install')
class TestLeadEvents(TransactionCase):

    def _extract(self, response, body='<p>Solicitud de grupo</p>'):
        lead = self.env['crm.lead'].create({'name': 'Petición de agencia'})
        with patch(LLM, return_value=(response, 'groq')):
            lead._restagrup_extract_from_email({'body': body})
        return lead

    # --- varios eventos en un mismo correo ---

    def test_three_events_become_three_draft_events(self):
        lead = self._extract(THREE_EVENTS)
        events = lead.restagrup_event_ids
        self.assertEqual(len(events), 3)
        self.assertEqual(set(events.mapped('state')), {'draft'})
        self.assertEqual(events.mapped('city'), ['Málaga', 'Málaga', 'Sevilla'])
        self.assertEqual([str(d) for d in events.mapped('event_date')], ['2026-11-15', '2026-11-15', '2026-11-16'])
        self.assertEqual(events.mapped('pax'), [42, 42, 40])
        self.assertEqual(events[0].notes, 'Sin gluten')

    def test_event_types_are_mapped_from_the_ai_keys(self):
        events = self._extract(THREE_EVENTS).restagrup_event_ids
        self.assertEqual(events[0].event_type_id, self.env.ref('restagrup_core.event_type_lunch'))
        self.assertEqual(events[1].event_type_id, self.env.ref('restagrup_core.event_type_dinner'))

    def test_unknown_event_type_falls_back_to_other_and_missing_one_stays_empty(self):
        data = {'eventos': [
            {'ciudad': 'Toledo', 'fecha': None, 'tipo': 'merienda-cena', 'pax': 10, 'notas': None},
            {'ciudad': 'Toledo', 'fecha': None, 'tipo': None, 'pax': 10, 'notas': None},
        ]}
        events = self._extract(data).restagrup_event_ids
        self.assertEqual(events[0].event_type_id, self.env.ref('restagrup_core.event_type_other'))
        self.assertFalse(events[1].event_type_id, 'Sin tipo en el correo: no se inventa.')

    def test_events_are_attached_to_the_lead_in_order(self):
        events = self._extract(THREE_EVENTS).restagrup_event_ids
        self.assertEqual(events.mapped('sequence'), sorted(events.mapped('sequence')))

    # --- compatibilidad con correos de un solo lugar y con los campos antiguos ---

    def test_single_event_email_creates_one_event(self):
        data = {'eventos': [{'ciudad': 'Málaga', 'fecha': '2026-11-15', 'tipo': 'cena', 'pax': 42, 'notas': None}]}
        self.assertEqual(len(self._extract(data).restagrup_event_ids), 1)

    def test_old_style_answer_without_events_list_builds_one_event(self):
        data = {'ciudad': 'Madrid', 'num_pax': 30, 'fecha_servicio': '2026-12-01', 'tipo_grupo': 'escolar'}
        events = self._extract(data).restagrup_event_ids
        self.assertEqual(len(events), 1)
        self.assertEqual((events.city, events.pax), ('Madrid', 30))

    def test_legacy_lead_fields_come_from_the_first_event(self):
        lead = self._extract({'eventos': THREE_EVENTS['eventos'], 'tipo_grupo': 'corporativo'})
        self.assertEqual(lead.restagrup_city, 'Málaga')
        self.assertEqual(lead.restagrup_pax, 42)
        self.assertEqual(str(lead.restagrup_service_date), '2026-11-15')

    def test_empty_answer_creates_no_events(self):
        lead = self._extract({'ciudad': None, 'num_pax': None, 'fecha_servicio': None, 'eventos': []})
        self.assertFalse(lead.restagrup_event_ids)

    def test_llm_failure_creates_no_events_and_flags_the_error(self):
        lead = self.env['crm.lead'].create({'name': 'Sin IA'})
        with patch(LLM, return_value=(None, None)):
            lead._restagrup_extract_from_email({'body': '<p>Hola</p>'})
        self.assertFalse(lead.restagrup_event_ids)
        self.assertEqual(lead.restagrup_extraction_state, 'error')

    # --- datos sucios: nunca rompen la extracción ---

    def test_invalid_date_keeps_the_event_without_date(self):
        data = {'eventos': [{'ciudad': 'Toledo', 'fecha': 'el 15 más o menos', 'tipo': 'cena', 'pax': 20, 'notas': None}]}
        events = self._extract(data).restagrup_event_ids
        self.assertEqual(len(events), 1)
        self.assertFalse(events.event_date)

    def test_non_numeric_pax_becomes_zero(self):
        data = {'eventos': [{'ciudad': 'Toledo', 'fecha': None, 'tipo': 'cena', 'pax': 'unas 40', 'notas': None}]}
        self.assertEqual(self._extract(data).restagrup_event_ids.pax, 0)

    def test_event_list_is_capped(self):
        many = {'eventos': [{'ciudad': 'C%s' % i, 'fecha': None, 'tipo': None, 'pax': 1, 'notas': None} for i in range(60)]}
        self.assertEqual(len(self._extract(many).restagrup_event_ids), 20)

    def test_events_that_are_not_objects_are_ignored(self):
        data = {'eventos': ['basura', None, {'ciudad': 'Toledo', 'fecha': None, 'tipo': None, 'pax': 5, 'notas': None}]}
        self.assertEqual(len(self._extract(data).restagrup_event_ids), 1)

    # --- el prompt conoce los eventos y la fecha de hoy ---

    def test_prompt_asks_for_events_and_gives_today_for_the_missing_year(self):
        lead = self.env['crm.lead'].create({'name': 'Prompt'})
        with patch(LLM, return_value=({'eventos': []}, 'groq')) as mock_llm:
            lead._restagrup_extract_from_email({'body': '<p>15 de noviembre, cena</p>'})
        system_prompt = mock_llm.call_args.args[0]
        self.assertIn('eventos', system_prompt)
        self.assertIn('coffee_break', system_prompt)
        self.assertRegex(system_prompt, r'\d{4}-\d{2}-\d{2}')

    # --- permisos: un comercial normal ---

    def test_salesperson_can_manage_events(self):
        user = self.env['res.users'].create({
            'name': 'Comercial eventos', 'login': 'comercial_eventos',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        lead = self.env['crm.lead'].with_user(user).create({'name': 'Lead del comercial'})
        event = self.env['restagrup.lead.event'].with_user(user).create({
            'lead_id': lead.id, 'city': 'Toledo', 'pax': 12,
        })
        event.write({'notes': 'Revisado'})
        self.assertEqual(event.notes, 'Revisado')
        event.unlink()
