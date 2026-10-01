# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

MARGIN_PARAM = 'restagrup.default_margin_percent'
MARGIN_NOTE = 'Gestión Restagrup'


@tagged('post_install', '-at_install')
class TestMarginTracking(TransactionCase):
    """El margen se guarda en la línea (coste del restaurante y % aplicado), se ve en la tabla
    interna y solo llega al cliente si el presupuesto tiene activado "mostrar margen"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(MARGIN_PARAM, '20')
        cls.client = cls.env['res.partner'].create({'name': 'Agencia margen', 'email': 'ag@example.com'})
        cls.restaurant = cls.env['res.partner'].create({'name': 'Asador margen', 'is_restaurant': True})
        cls.menu = cls.env['product.template'].create({
            'name': 'Menú margen', 'type': 'service', 'standard_price': 25.0,
            'sale_ok': True, 'restaurant_id': cls.restaurant.id,
        })

    def _order(self, qty=42, product=None):
        product = product or self.menu.product_variant_id
        return self.env['sale.order'].create({
            'partner_id': self.client.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': qty})],
        })

    def _quote_order(self, amount=1000):
        """Presupuesto de venta creado desde una petición sin menús (importe de restaurante)."""
        restaurant = self.env['res.partner'].create({'name': 'Sin menús', 'is_restaurant': True})
        lead = self.env['crm.lead'].create({'name': 'Grupo margen', 'partner_id': self.client.id})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Toledo', 'min_capacity': 30,
        })
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': 'Elegido',
            'partner_id': restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': amount,
        })
        line.action_toggle_chosen()
        search.action_create_sale_order()
        return search.sale_order_id

    # --- coste y margen por línea ---

    def test_menu_line_stores_restaurant_cost_and_applied_margin(self):
        line = self._order(qty=42).order_line
        self.assertEqual(line.restagrup_unit_cost, 25.0)
        self.assertEqual(line.restagrup_margin_pct, 20.0)
        self.assertEqual(line.price_unit, 30.0)
        self.assertEqual(line.restagrup_margin_amount, 210.0)  # 42 x (30 - 25)

    def test_quote_line_cost_is_the_restaurant_quote(self):
        line = self._quote_order(amount=1000).order_line
        self.assertEqual(line.restagrup_unit_cost, 1000.0)
        self.assertEqual(line.price_unit, 1200.0)
        self.assertEqual(line.restagrup_margin_amount, 200.0)
        self.assertEqual(line.restagrup_margin_pct, 20.0)

    def test_line_without_restaurant_has_no_margin(self):
        product = self.env['product.product'].create({'name': 'Extra', 'type': 'service', 'list_price': 50.0})
        line = self._order(qty=2, product=product).order_line
        self.assertEqual(line.restagrup_unit_cost, 0.0)
        self.assertEqual(line.restagrup_margin_amount, 0.0)

    def test_margin_is_frozen_when_settings_change_later(self):
        order = self._order(qty=10)
        self.env['ir.config_parameter'].sudo().set_param(MARGIN_PARAM, '50')
        order.order_line.product_uom_qty = 50  # cambian los comensales
        self.assertEqual(order.order_line.restagrup_margin_pct, 20.0)
        self.assertEqual(order.order_line.price_unit, 30.0, 'El precio no debe saltar al 50 % nuevo.')

    def test_new_lines_use_the_current_margin(self):
        self.env['ir.config_parameter'].sudo().set_param(MARGIN_PARAM, '50')
        line = self._order(qty=10).order_line
        self.assertEqual(line.restagrup_margin_pct, 50.0)
        self.assertEqual(line.price_unit, 37.5)

    # --- totales del presupuesto ---

    def test_order_margin_totals(self):
        order = self._order(qty=42)
        order.write({'order_line': [(0, 0, {
            'product_id': self.menu.product_variant_id.id, 'product_uom_qty': 8,
        })]})
        self.assertEqual(order.restagrup_cost_total, 1250.0)   # 50 x 25
        self.assertEqual(order.restagrup_margin_total, 250.0)  # 50 x 5
        self.assertEqual(order.restagrup_margin_percent, 20.0)

    def test_order_without_restaurant_lines_has_zero_margin(self):
        product = self.env['product.product'].create({'name': 'Extra 2', 'type': 'service', 'list_price': 10.0})
        order = self._order(qty=1, product=product)
        self.assertEqual(order.restagrup_margin_total, 0.0)
        self.assertEqual(order.restagrup_margin_percent, 0.0)

    # --- interruptor "mostrar margen al cliente" ---

    def test_show_margin_is_off_by_default_and_not_copied(self):
        order = self._order()
        self.assertFalse(order.restagrup_show_margin)
        order.restagrup_show_margin = True
        self.assertFalse(order.copy().restagrup_show_margin)

    def _pdf_html(self, order):
        html, _kind = self.env['ir.actions.report']._render_qweb_html('sale.action_report_saleorder', order.ids)
        return html.decode()

    def test_pdf_hides_margin_by_default(self):
        self.assertNotIn(MARGIN_NOTE, self._pdf_html(self._order()))

    def test_pdf_shows_margin_note_when_switch_is_on(self):
        order = self._order(qty=42)
        order.restagrup_show_margin = True
        html = self._pdf_html(order)
        self.assertIn(MARGIN_NOTE, html)
        self.assertIn('20', html)
        self.assertIn('210', html)

    def test_pdf_never_shows_the_restaurant_cost(self):
        order = self._order(qty=42)
        order.restagrup_show_margin = True
        html = self._pdf_html(order)
        self.assertNotIn('1.050', html)  # 42 x 25 = coste del restaurante
        self.assertNotIn('1,050', html)

    # --- permisos: un comercial (sin Compras ni administración) ve y usa el margen ---

    def test_salesperson_can_see_margin_and_use_the_switch(self):
        user = self.env['res.users'].create({
            'name': 'Comercial margen', 'login': 'comercial_margen',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        order = self.env['sale.order'].with_user(user).create({
            'partner_id': self.client.id,
            'order_line': [(0, 0, {'product_id': self.menu.product_variant_id.id, 'product_uom_qty': 42})],
        })
        self.assertEqual(order.order_line.restagrup_margin_amount, 210.0)
        self.assertEqual(order.restagrup_margin_total, 210.0)
        order.restagrup_show_margin = True
        self.assertTrue(order.restagrup_show_margin)
