# -*- coding: utf-8 -*-
from lxml import etree

from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestServicePricePerPerson(TransactionCase):
    """Punto 6 (ronda 11/11, respuesta en la reunión del 12/11): en la lista de servicios del grupo se ve el
    precio del menú por persona que paga la agencia (16,80 €), no el total del restaurante (588 €)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        agency = cls.env['res.partner'].create({'name': 'Agencia punto 6', 'email': 'ag6@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo punto 6', 'partner_id': agency.id})
        restaurant = cls.env['res.partner'].create({
            'name': 'Mesón punto 6', 'is_restaurant': True, 'email': 'r6@example.com'})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Sevilla', 'pax': 42, 'event_date': '2026-12-15',
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id,
        })
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Sevilla', 'min_capacity': 42,
        })
        cls.line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 14.0,
        })
        cls.line.action_toggle_chosen()

    def test_event_shows_agency_price_per_person_of_chosen_restaurant(self):
        self.assertTrue(self.line.quote_client_price_per_person)
        self.assertNotEqual(self.line.quote_client_price_per_person, 14.0)  # lleva la comisión
        self.assertEqual(self.event.chosen_price_pp, self.line.quote_client_price_per_person)

    def test_event_without_chosen_restaurant_has_no_price(self):
        self.line.action_toggle_chosen()
        self.assertFalse(self.event.chosen_price_pp)

    def test_services_list_shows_price_per_person_and_hides_total(self):
        arch = self.env['crm.lead'].get_views([(False, 'form')])['views']['form']['arch']
        services = etree.fromstring(arch).xpath("//field[@name='restagrup_event_ids']/list")[0]
        price = services.xpath("field[@name='chosen_price_pp']")
        self.assertTrue(price, 'Falta el precio por persona en la lista de servicios')
        self.assertNotEqual(price[0].get('column_invisible'), '1')
        total = services.xpath("field[@name='chosen_amount']")
        self.assertTrue(not total or total[0].get('optional') == 'hide',
                        'El total del restaurante no debe verse por defecto')
