# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLeadPaidOnCreate(TransactionCase):
    """Prueba en prod 12/11: crear un grupo a mano daba «no hay nada que marcar como pagado» porque el formulario
    manda Pagado = No y la inversa lo trataba como desmarcar el pago."""

    def test_new_group_from_the_form_saves(self):
        with Form(self.env['crm.lead']) as form:
            form.name = 'Grupo creado a mano'
        self.assertTrue(form.record.id)
        self.assertFalse(form.record.restagrup_paid)

    def test_create_with_paid_false_is_fine(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo', 'restagrup_paid': False})
        self.assertFalse(lead.restagrup_paid)

    def test_marking_paid_without_order_still_says_so(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo'})
        with self.assertRaises(UserError):
            lead.restagrup_paid = True
