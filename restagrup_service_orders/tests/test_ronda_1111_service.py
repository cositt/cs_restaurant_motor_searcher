# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11 (Conchita), en la ficha del grupo:

- Una petición dada de alta a mano (por teléfono) mostraba en el título el ejemplo de Odoo «p. ej. Precios de
  productos». Ahora pide el nombre del grupo.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRonda1111Service(TransactionCase):

    def test_group_name_placeholder_speaks_about_groups(self):
        arch = self.env['crm.lead'].get_view(self.env.ref('crm.crm_lead_view_form').id, 'form')['arch']
        self.assertNotIn('Precios de productos', arch)
        self.assertIn('Nombre del grupo', arch)
