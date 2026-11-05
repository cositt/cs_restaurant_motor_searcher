# -*- coding: utf-8 -*-
"""«Aceptar y firmar» y «Rechazar» son de la agencia: en la vista previa de un empleado no salen y no
funcionan (PPT de Conchita 2026-11-04, diapositiva 8). La demo puede permitirlo con un parámetro."""
from odoo.tests.common import TransactionCase, tagged

PARAM = 'restagrup.portal_staff_can_sign'


@tagged('post_install', '-at_install')
class TestStaffPreview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(PARAM, False)
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia Preview', 'email': 'a@preview.example.com'})
        product = cls.env.ref('restagrup_service_orders.product_restaurant_service')
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.agency.id, 'require_signature': True,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 10, 'price_unit': 30})]})
        cls.employee = cls.env.ref('base.user_admin')
        cls.portal_user = cls.env['res.users'].create({
            'name': 'Agencia Portal', 'login': 'agencia.preview@example.com', 'partner_id': cls.agency.id,
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])]})

    def test_employee_preview_cannot_sign(self):
        self.assertTrue(self.order._has_to_be_signed())
        self.assertFalse(self.order._restagrup_customer_actions_allowed(self.employee))
        preview = self.order._restagrup_portal_order(self.employee)
        self.assertFalse(preview._has_to_be_signed())
        self.assertFalse(preview._has_to_be_paid())

    def test_agency_can_sign(self):
        self.assertTrue(self.order._restagrup_customer_actions_allowed(self.portal_user))
        self.assertTrue(self.order._restagrup_portal_order(self.portal_user)._has_to_be_signed())

    def test_public_link_can_sign(self):
        public = self.env.ref('base.public_user')
        self.assertTrue(self.order._restagrup_customer_actions_allowed(public))

    def test_demo_can_allow_staff_to_sign(self):
        self.env['ir.config_parameter'].sudo().set_param(PARAM, 'True')
        self.assertTrue(self.order._restagrup_customer_actions_allowed(self.employee))
