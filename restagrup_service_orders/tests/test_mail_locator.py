# -*- coding: utf-8 -*-
"""Todos los correos llevan el localizador del grupo (PET…) en el asunto y en el texto; la petición de
presupuesto al restaurante, con su asunto «Presupuesto para grupos — …». La agencia se ve en la cola, nunca
en lo que recibe el restaurante (PPT de Conchita 2026-11-04, diapositiva 4)."""
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMailLocator(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia Clandestina', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Erika Zarandona', 'parent_id': cls.agency.id, 'email': 'erika@clandestina.example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Teresianas', 'partner_id': cls.contact.id})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'pax': 30, 'event_date': date(2027, 2, 1),
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Málaga', 'min_capacity': 30})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante La Fría', 'is_restaurant': True, 'email': 'reservas@lafria.example.com'})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'email': cls.restaurant.email})
        cls.locator = cls.lead.restagrup_doc_number

    def test_quote_request_subject(self):
        self.line.action_request_quote()
        message = self.line.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        self.assertTrue(message.subject.startswith('Presupuesto para grupos — %s' % self.locator), message.subject)
        self.assertIn('Málaga', message.subject)
        self.assertIn('01/02/2027', message.subject)

    def test_quote_request_body_has_the_locator_but_not_the_agency(self):
        self.line.action_request_quote()
        message = self.line.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
        self.assertIn(self.locator, message.body)
        self.assertNotIn('Clandestina', message.body)
        self.assertNotIn('Clandestina', message.subject)

    def _pending(self, **vals):
        return self.env['restagrup.pending.mail'].create(dict({
            'kind': 'quote_reminder', 'line_id': self.line.id, 'recipient_email': self.restaurant.email,
            'subject': 'Recordatorio: consulta de disponibilidad', 'body': 'Hola,\n\n¿Tenéis disponibilidad?'}, **vals))

    def test_queued_mail_gets_the_locator(self):
        mail = self._pending()
        self.assertIn(self.locator, mail.subject)
        self.assertIn(self.locator, mail.body)

    def test_locator_is_not_repeated(self):
        mail = self._pending(subject='Recordatorio — %s' % self.locator, body='Ref. %s\n\nHola' % self.locator)
        self.assertEqual(mail.subject.count(self.locator), 1)
        self.assertEqual(mail.body.count(self.locator), 1)

    def test_queue_shows_the_agency_only_to_the_team(self):
        mail = self._pending()
        self.assertEqual(mail.agency_name, 'Agencia Clandestina')
        self.assertNotIn('Clandestina', mail.body)
        arch = self.env['restagrup.pending.mail'].get_view(view_type='list')['arch']
        self.assertIn('name="agency_name"', arch)

    def test_locator_marker_in_templates(self):
        self.assertEqual(self.line._mail_values('Ana')['localizador'], self.locator)
