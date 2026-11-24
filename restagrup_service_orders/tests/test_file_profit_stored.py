# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFileProfitStored(TransactionCase):
    """Tablero (reunión 23/11): el beneficio de la petición se guarda para poder sumarlo por día en gráficas y tableros.
    Es lo facturado a la agencia menos lo que cobran los restaurantes, sin contar presupuestos cancelados."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.client = cls.env['res.partner'].create({'name': 'Agencia beneficio', 'email': 'ag@example.com'})
        restaurant = cls.env['res.partner'].create({'name': 'Asador beneficio', 'is_restaurant': True})
        cls.menu = cls.env['product.template'].create({
            'name': 'Menú beneficio', 'type': 'service', 'standard_price': 25.0,
            'sale_ok': True, 'restaurant_id': restaurant.id,
        })

    def _lead_with_order(self, qty=40):
        lead = self.env['crm.lead'].create({'name': 'Grupo beneficio', 'partner_id': self.client.id})
        order = self.env['sale.order'].create({
            'partner_id': self.client.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.menu.product_variant_id.id, 'product_uom_qty': qty})],
        })
        return lead, order

    def test_profit_is_a_stored_field(self):
        self.assertTrue(self.env['crm.lead']._fields['restagrup_profit'].store)

    def test_profit_is_the_commission_of_the_group(self):
        lead, order = self._lead_with_order()
        self.assertGreater(order.restagrup_margin_total, 0)
        self.assertAlmostEqual(lead.restagrup_profit, order.restagrup_margin_total, places=2)
        self.assertAlmostEqual(lead.restagrup_profit, lead.restagrup_total_commission, places=2)

    def test_profit_follows_changes_in_the_quote(self):
        lead, order = self._lead_with_order(qty=40)
        before = lead.restagrup_profit
        order.order_line.product_uom_qty = 80
        self.assertAlmostEqual(lead.restagrup_profit, before * 2, places=2)

    def test_cancelled_quote_does_not_count(self):
        lead, order = self._lead_with_order()
        order._action_cancel()
        self.assertEqual(lead.restagrup_profit, 0.0)

    def test_lead_without_quote_has_no_profit(self):
        lead = self.env['crm.lead'].create({'name': 'Sin presupuesto'})
        self.assertEqual(lead.restagrup_profit, 0.0)

    def test_profit_can_be_summed_in_graphs(self):
        lead, order = self._lead_with_order()
        rows = self.env['crm.lead']._read_group([('id', '=', lead.id)], [], ['restagrup_profit:sum'])
        self.assertAlmostEqual(rows[0][0], order.restagrup_margin_total, places=2)
