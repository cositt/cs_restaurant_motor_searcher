# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRonda2011Notes(TransactionCase):
    """Ronda 20/11 (6): el contacto del guía y las intolerancias del grupo pasan solos a «Notas para agencia y
    restaurante», para que salgan en lo que se manda al restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo notas 2011'})

    def _event(self, **vals):
        base = {
            'lead_id': self.lead.id, 'city': 'Cuenca', 'pax': 55,
            'event_date': fields.Date.context_today(self.lead) + timedelta(days=3),
            'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id,
        }
        return self.env['restagrup.lead.event'].create({**base, **vals})

    def test_guide_and_no_allergies_go_to_the_notes(self):
        event = self._event()
        event.write({'guide_contact': 'Conchita 618353422', 'no_intolerances': True})
        self.assertIn('Contacto del guía: Conchita 618353422', event.notes)
        self.assertIn('Sin intolerancias ni alergias', event.notes)

    def test_changing_the_guide_replaces_the_line_and_keeps_other_notes(self):
        event = self._event(notes='Entrada por la puerta de atrás')
        event.guide_contact = 'Ana 600111222'
        event.guide_contact = 'Luis 600333444'
        self.assertIn('Entrada por la puerta de atrás', event.notes)
        self.assertIn('Contacto del guía: Luis 600333444', event.notes)
        self.assertNotIn('Ana', event.notes)
        self.assertEqual(event.notes.count('Contacto del guía'), 1)

    def test_intolerances_text_replaces_the_no_allergies_line(self):
        event = self._event(no_intolerances=True)
        self.assertIn('Sin intolerancias ni alergias', event.notes)
        event.write({'no_intolerances': False, 'intolerances': '2 celíacos'})
        self.assertIn('Intolerancias: 2 celíacos', event.notes)
        self.assertNotIn('Sin intolerancias', event.notes)

    def test_clearing_a_field_removes_its_line(self):
        event = self._event(guide_contact='Ana 600111222', notes='Nota propia')
        event.guide_contact = False
        self.assertNotIn('Contacto del guía', event.notes or '')
        self.assertIn('Nota propia', event.notes)

    def test_events_without_those_fields_keep_their_notes_untouched(self):
        event = self._event(notes='Solo esto')
        event.pax = 60
        self.assertEqual(event.notes, 'Solo esto')
