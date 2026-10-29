# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

PENDING = 'Pendiente de asignación'


@tagged('post_install', '-at_install')
class TestLeadAssignment(TransactionCase):
    """Cada petición enseña quién la lleva; si aún no la lleva nadie, «Pendiente de asignación» (en rojo en las listas)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env['crm.lead'].with_context(restagrup_skip_firewall=True)
        cls.ana = cls.env['res.users'].create({
            'name': 'Ana Asignación', 'login': 'ana_asignacion',
            'group_ids': [(4, cls.env.ref('sales_team.group_sale_salesman_all_leads').id)]})

    def test_assigned_lead_shows_who_carries_it(self):
        lead = self.Lead.create({'name': 'Grupo asignado', 'user_id': self.ana.id})
        self.assertEqual(lead.restagrup_assignee_label, 'Ana Asignación')

    def test_lead_without_responsible_is_pending_assignment(self):
        lead = self.Lead.create({'name': 'Grupo sin asignar', 'user_id': False})
        self.assertEqual(lead.restagrup_assignee_label, PENDING)
        lead.user_id = self.ana
        self.assertEqual(lead.restagrup_assignee_label, 'Ana Asignación')

    def test_request_from_email_arrives_unassigned(self):
        with patch('odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
                   return_value=({'eventos': []}, 'groq')):
            lead = self.env['crm.lead'].with_context(mail_create_nolog=True).message_new({
                'subject': 'Petición grupo', 'email_from': 'agencia@example.com', 'body': '<p>Hola</p>',
                'from': 'agencia@example.com', 'to': 'peticiones@example.com'})
        self.assertFalse(lead.user_id, 'el usuario del servidor de correo no debe quedar como responsable')
        self.assertEqual(lead.restagrup_assignee_label, PENDING)

    def test_unassigned_filter_finds_only_unassigned_leads(self):
        free = self.Lead.create({'name': 'Libre', 'user_id': False})
        taken = self.Lead.create({'name': 'Cogido', 'user_id': self.ana.id})
        search_view = self.env.ref('restagrup_service_orders.view_crm_lead_restagrup_search')
        self.assertIn('name="unassigned"', search_view.arch)
        found = self.env['crm.lead'].search([('user_id', '=', False), ('id', 'in', (free | taken).ids)])
        self.assertEqual(found, free)
