# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestServiceChangesReachOrder(TransactionCase):
    """Reunión 12/11 (7.5): la hora y el tipo puestos en el servicio después de crear el pedido no llegaban al
    pedido, y la confirmación al restaurante seguía diciendo «Falta la fecha o la hora del servicio»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        agency = cls.env['res.partner'].create({'name': 'Agencia 1211', 'email': 'ag1211@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo escolar 1211', 'partner_id': agency.id})
        restaurant = cls.env['res.partner'].create({
            'name': 'Ribs 1211', 'is_restaurant': True, 'email': 'ribs1211@example.com'})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 42, 'event_date': '2026-12-11',
        })
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Madrid', 'min_capacity': 42,
        })
        line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 12.0,
        })
        line.action_toggle_chosen()
        search.action_create_sale_order()
        cls.order = search.sale_order_id
        cls.sale_line = cls.order.order_line.filtered('restaurant_id')

    def test_hour_and_type_set_later_on_the_service_reach_the_order(self):
        self.event.write({
            'event_time': 13.5, 'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id,
        })
        self.assertEqual(self.sale_line.service_hour, 13.5)
        self.assertEqual(self.sale_line.service_event_type_id, self.env.ref('restagrup_core.event_type_lunch'))

    def test_date_change_on_the_service_reaches_the_order(self):
        self.event.event_date = '2026-12-12'
        self.assertEqual(str(self.sale_line.service_date), '2026-12-12')

    def test_restaurant_confirmation_no_longer_complains_after_setting_the_hour(self):
        self.event.event_time = 13.5
        self.order.action_confirm()
        purchase = self.order.sudo().restaurant_po_ids[:1]
        self.assertTrue(purchase)
        self.assertFalse(purchase._fw_service_datetime())
