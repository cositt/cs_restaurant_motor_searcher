# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSalesOnlyUser(TransactionCase):
    """Un comercial (sin permisos de Compras) tiene que poder trabajar con todo el flujo:
    las hojas de servicio son pedidos de compra que genera el sistema, no algo que
    él gestione. Los tests como superusuario no detectan esto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salesman = cls.env['res.users'].create({
            'name': 'Comercial sin compras', 'login': 'comercial_sin_compras',
            'email': 'comercial@example.test',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia permisos', 'email': 'agencia@example.test'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante permisos', 'is_restaurant': True, 'email': 'rest@example.test',
        })
        cls.menu = cls.env['product.template'].create({
            'name': 'Menú permisos', 'type': 'service', 'standard_price': 28.0,
            'sale_ok': True, 'restaurant_id': cls.restaurant.id,
        })

    def _order_as_salesman(self):
        return self.env['sale.order'].with_user(self.salesman).create({
            'partner_id': self.agency.id,
            'order_line': [(0, 0, {'product_id': self.menu.product_variant_id.id, 'product_uom_qty': 15})],
        })

    def test_salesman_can_read_restaurant_flags_on_contacts(self):
        partner = self.restaurant.with_user(self.salesman)
        self.assertFalse(partner.read(['restaurant_worked_with'])[0]['restaurant_worked_with'])

    def test_salesman_can_open_own_order_before_and_after_confirming(self):
        order = self._order_as_salesman()
        fields_read = ['restaurant_po_count', 'restaurant_changes_pending',
                       'restagrup_confirmed_count', 'restagrup_pending_count',
                       'restagrup_confirmation_summary']
        order.read(fields_read)
        order.action_confirm()
        values = order.read(fields_read)[0]
        self.assertEqual(values['restaurant_po_count'], 1)
        self.assertEqual(values['restagrup_pending_count'], 1)
        self.assertEqual(values['restagrup_confirmation_summary'], '0/1')

    def test_salesman_confirming_creates_the_service_sheet(self):
        order = self._order_as_salesman()
        order.action_confirm()
        self.assertEqual(len(order.sudo().restaurant_po_ids), 1)

    def test_salesman_can_send_sheets_and_resend_changes(self):
        order = self._order_as_salesman()
        order.action_confirm()
        order.action_send_restaurant_orders()
        self.assertEqual(order.sudo().restaurant_po_ids.state, 'sent')
        order.order_line[0].product_uom_qty = 18
        order.action_resend_restaurant_orders()
        self.assertFalse(order.sudo().restaurant_po_ids.restagrup_needs_resend)

    def test_partner_flag_still_true_after_a_sheet_exists(self):
        order = self._order_as_salesman()
        order.action_confirm()
        partner = self.restaurant.with_user(self.salesman)
        self.assertTrue(partner.read(['restaurant_worked_with'])[0]['restaurant_worked_with'])
