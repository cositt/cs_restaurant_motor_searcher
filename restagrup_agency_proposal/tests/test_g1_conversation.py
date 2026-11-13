# -*- coding: utf-8 -*-
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestG1Conversation(TransactionCase):
    """Reunión 12/11 (6.2): en la pestaña Conversación, cambiar «Ver» (Agencia / Restaurantes) no filtraba: la
    ficha recalcula sobre un registro temporal y la conversación se quedaba vacía."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.agency = Partner.create({'name': 'Agencia Conv', 'email': 'agencia-conv@example.com'})
        cls.restaurant = Partner.create({'name': 'Rest Conv', 'is_restaurant': True, 'email': 'rest-conv@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo Conv', 'partner_id': cls.agency.id})
        search = cls.env['restagrup.restaurant.search'].create({'lead_id': cls.lead.id, 'city': 'Madrid'})
        line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Rest Conv', 'partner_id': cls.restaurant.id})
        cls.lead.message_post(body='Mensaje de la agencia', message_type='email', author_id=cls.agency.id)
        line.message_post(body='Mensaje del restaurante', message_type='email', author_id=cls.restaurant.id)

    def _html_with_filter(self, wanted):
        with Form(self.lead) as form:
            form.restagrup_conversation_filter = wanted
            return str(form.restagrup_conversation_html or '')

    def test_filter_restaurants_in_the_form(self):
        html = self._html_with_filter('restaurant')
        self.assertIn('Mensaje del restaurante', html)
        self.assertNotIn('Mensaje de la agencia', html)

    def test_filter_agency_in_the_form(self):
        html = self._html_with_filter('agency')
        self.assertIn('Mensaje de la agencia', html)
        self.assertNotIn('Mensaje del restaurante', html)

    def test_filter_all_in_the_form(self):
        html = self._html_with_filter('all')
        self.assertIn('Mensaje de la agencia', html)
        self.assertIn('Mensaje del restaurante', html)
