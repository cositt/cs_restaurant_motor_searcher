# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRestaurantSearchSale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_partner = cls.env['res.partner'].create({'name': 'Cliente Test'})
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Grupo de prueba', 'partner_id': cls.client_partner.id,
        })
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 20,
        })
        cls.restaurant_partner = cls.env['res.partner'].create({
            'name': 'Restaurante Test', 'is_restaurant': True, 'city': 'Madrid',
        })

    def _create_chosen_line(self, search=None, quote_amount=200):
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': (search or self.search).id, 'source': 'partner', 'name': 'Restaurante Test',
            'partner_id': self.restaurant_partner.id, 'etiqueta': 'presupuesto_recibido',
            'quote_amount': quote_amount,
        })
        line.action_toggle_chosen()
        return line

    def test_create_sale_order_requires_chosen_line(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        with self.assertRaises(UserError):
            search.action_create_sale_order()

    def test_create_sale_order_requires_partner_contact(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'google', 'name': 'Sin contacto',
            'etiqueta': 'presupuesto_recibido', 'quote_amount': 100,
        })
        line.action_toggle_chosen()
        with self.assertRaises(UserError):
            search.action_create_sale_order()

    def test_create_sale_order_requires_lead_partner(self):
        lead_no_partner = self.env['crm.lead'].create({'name': 'Sin cliente'})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead_no_partner.id, 'city': 'Madrid',
        })
        self._create_chosen_line(search=search)
        with self.assertRaises(UserError):
            search.action_create_sale_order()

    def test_create_sale_order_creates_correct_line(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        line = self._create_chosen_line(search=search, quote_amount=200)
        search.action_create_sale_order()
        order = search.sale_order_id
        self.assertTrue(order)
        self.assertEqual(order.partner_id, self.client_partner)
        self.assertEqual(len(order.order_line), 1)
        sale_line = order.order_line[0]
        self.assertEqual(sale_line.restaurant_id, self.restaurant_partner)
        self.assertEqual(sale_line.restagrup_search_line_id, line)
        self.assertAlmostEqual(sale_line.price_unit, 240.0)  # sin ajuste configurado: +20 %

    # --- con importe cotizado: una línea con cantidad = comensales y precio por persona ---

    def _per_person_search(self, pax, quote_amount):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid', 'min_capacity': pax,
        })
        self._create_chosen_line(search=search, quote_amount=quote_amount)
        search.action_create_sale_order()
        return search.sale_order_id

    def test_quote_becomes_one_line_per_person(self):
        order = self._per_person_search(32, 1024)
        line = order.order_line
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_uom_qty, 32)
        self.assertAlmostEqual(line.restagrup_unit_cost, 32.0)  # 1.024 / 32
        self.assertAlmostEqual(line.price_unit, 38.4)           # 32 + 20 %
        self.assertAlmostEqual(order.amount_untaxed, 1228.8)    # 1.024 + 20 %
        self.assertAlmostEqual(line.restagrup_margin_amount, 204.8)

    def test_without_headcount_the_quote_stays_one_global_line(self):
        order = self._per_person_search(0, 1000)
        self.assertEqual(order.order_line.product_uom_qty, 1)
        self.assertAlmostEqual(order.order_line.restagrup_unit_cost, 1000.0)
        self.assertAlmostEqual(order.amount_untaxed, 1200.0)

    def test_service_sheet_carries_the_per_person_cost(self):
        order = self._per_person_search(32, 1024)
        order.action_confirm()
        po_line = order.restaurant_po_ids.order_line
        self.assertEqual(po_line.product_qty, 32)
        self.assertAlmostEqual(po_line.price_unit, 32.0)
        self.assertAlmostEqual(po_line.price_subtotal, 1024.0)

    def test_create_sale_order_respects_an_explicit_zero_margin(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '0')
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self._create_chosen_line(search=search, quote_amount=200)
        search.action_create_sale_order()
        self.assertAlmostEqual(search.sale_order_id.order_line[0].price_unit, 200.0)

    def test_service_sheet_carries_the_restaurant_quote_not_the_client_price(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self._create_chosen_line(search=search, quote_amount=200)
        search.action_create_sale_order()
        order = search.sale_order_id
        self.assertAlmostEqual(order.order_line.price_unit, 240.0)
        order.action_confirm()
        self.assertAlmostEqual(order.restaurant_po_ids.order_line.price_unit, 200.0)

    def test_create_sale_order_applies_margin(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self._create_chosen_line(search=search, quote_amount=200)
        search.action_create_sale_order()
        sale_line = search.sale_order_id.order_line[0]
        self.assertEqual(sale_line.price_unit, 240.0)

    def test_create_sale_order_is_idempotent(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self._create_chosen_line(search=search, quote_amount=200)
        search.action_create_sale_order()
        first_order = search.sale_order_id
        action = search.action_create_sale_order()
        self.assertEqual(search.sale_order_id, first_order)
        self.assertEqual(action['res_id'], first_order.id)

    def test_pipeline_stage_sale_created(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self._create_chosen_line(search=search, quote_amount=200)
        self.assertEqual(search.pipeline_stage, 'chosen')
        search.action_create_sale_order()
        self.assertEqual(search.pipeline_stage, 'sale_created')

    def test_restaurant_worked_with_reflects_purchase_orders(self):
        partner = self.env['res.partner'].create({'name': 'Otro Rest', 'is_restaurant': True})
        self.assertFalse(partner.restaurant_worked_with)
        po = self.env['purchase.order'].create({'partner_id': partner.id})
        self.assertTrue(partner.restaurant_worked_with)
        po.write({'state': 'cancel'})
        self.assertFalse(partner.restaurant_worked_with)
