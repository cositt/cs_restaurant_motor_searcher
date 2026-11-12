# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11: «Pedir presupuestos a interesados» decía que no había email, pero Los Arcos sí lo tiene.

Los Arcos ya no estaba como interesado: Rubén le había puesto el presupuesto con el precio del catálogo. Solo quedaba
Flor de Sal (de Google, sin email). El aviso ahora explica las dos cosas: quién no tiene email y quién ya tiene
presupuesto de catálogo con la disponibilidad sin confirmar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRonda1111BulkQuote(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        lead = cls.env['crm.lead'].create({'name': 'Grupo adulto'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 42})
        arcos = cls.env['res.partner'].create({
            'name': 'Mesón Arcos Test', 'is_restaurant': True, 'city': 'Sevilla', 'email': 'arcos@test.example'})
        cls.arcos = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': arcos.name, 'partner_id': arcos.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 14.0, 'quote_availability_pending': True})
        cls.google = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'google', 'name': 'Flor De Sal Test', 'etiqueta': 'interesado'})

    def test_message_explains_no_email_and_catalogue_quote(self):
        with self.assertRaises(UserError) as error:
            self.search.action_request_quote_interested()
        text = str(error.exception)
        self.assertIn('Flor De Sal Test', text)
        self.assertIn('Mesón Arcos Test', text)
        self.assertIn('catálogo', text)

    def test_no_interested_mentions_the_catalogue_ones(self):
        self.google.etiqueta = 'descartado'
        with self.assertRaises(UserError) as error:
            self.search.action_request_quote_interested()
        self.assertIn('Mesón Arcos Test', str(error.exception))
