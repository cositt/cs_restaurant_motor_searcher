# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: toda la conversación del grupo en una pestaña.

Los correos con la agencia (grupo y pedido) y con los restaurantes (peticiones de presupuesto y hojas) en un solo
hilo, del más reciente al más antiguo, con un color por interlocutor (agencia, restaurante, RestaGrup) y un filtro.
"""
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRonda0911Conversation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({
            'name': 'Agencia Charla', 'is_company': True, 'email': 'charla@agencia.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Charla', 'is_restaurant': True, 'email': 'charla@casa.example', 'city': 'Sevilla'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo charla', 'partner_id': cls.agency.id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Sevilla', 'min_capacity': 20})
        cls.line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id})
        cls.lead.message_post(body='Somos 40 el día 15', message_type='email', author_id=cls.agency.id)
        cls.line.message_post(body='Tenemos sitio, 18 euros', message_type='email', author_id=cls.restaurant.id)
        cls.line.message_post(body='¿Tenéis sitio para 40?', message_type='email',
                              author_id=cls.env.user.partner_id.id)
        cls.lead.message_post(body='nota interna que no es conversación', message_type='notification')
        cls.lead.message_post(body='otra nota interna escrita a mano', message_type='comment',
                              subtype_xmlid='mail.mt_note')

    def test_everything_in_one_thread_with_its_colour(self):
        html = str(self.lead.restagrup_conversation_html)
        self.assertIn('Somos 40 el día 15', html)
        self.assertIn('Tenemos sitio, 18 euros', html)
        self.assertIn('¿Tenéis sitio para 40?', html)
        for kind in ('o_rg_msg_agency', 'o_rg_msg_restaurant', 'o_rg_msg_restagrup'):
            self.assertIn(kind, html)
        self.assertNotIn('nota interna', html)
        self.assertIn('Casa Charla', html)

    def test_filter_only_restaurants(self):
        self.lead.restagrup_conversation_filter = 'restaurant'
        html = str(self.lead.restagrup_conversation_html)
        self.assertIn('Tenemos sitio, 18 euros', html)
        self.assertIn('¿Tenéis sitio para 40?', html)
        self.assertNotIn('Somos 40 el día 15', html)

    def test_filter_only_agency(self):
        self.lead.restagrup_conversation_filter = 'agency'
        html = str(self.lead.restagrup_conversation_html)
        self.assertIn('Somos 40 el día 15', html)
        self.assertNotIn('Tenemos sitio', html)

    def test_the_tab_is_on_the_group(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        self.assertIn('name="restagrup_conversation"', arch)
        self.assertIn('name="restagrup_conversation_filter"', arch)
