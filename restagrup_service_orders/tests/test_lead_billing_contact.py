# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLeadBillingContact(TransactionCase):
    """Un lead nacido de un correo llega sin contacto: al crear el presupuesto de venta se busca el
    contacto por email o se crea con los datos del remitente."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante Test', 'is_restaurant': True, 'city': 'Madrid',
            'email': 'eleanor@sunrise.test',
        })

    def _chosen_search(self, lead):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 20,
        })
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': 200,
        })
        line.action_toggle_chosen()
        return search

    def _email_lead(self, email_from='"Eleanor Whitfield" <eleanor@sunrise.test>', **vals):
        return self.env['crm.lead'].create(dict({'name': 'Solicitud por correo', 'email_from': email_from}, **vals))

    def test_creates_contact_from_sender(self):
        lead = self._email_lead(phone='+44 161 555 0142')
        self.assertFalse(lead.partner_id)
        search = self._chosen_search(lead)
        search.action_create_sale_order()
        client = lead.partner_id
        self.assertTrue(client)
        self.assertEqual(client.name, 'Eleanor Whitfield')
        self.assertEqual(client.email, 'eleanor@sunrise.test')
        self.assertFalse(client.is_restaurant)
        self.assertEqual(search.sale_order_id.partner_id, client)

    def test_reuses_existing_contact_by_email(self):
        existing = self.env['res.partner'].create({'name': 'Eleanor W.', 'email': 'Eleanor@Sunrise.test'})
        lead = self._email_lead()
        search = self._chosen_search(lead)
        search.action_create_sale_order()
        self.assertEqual(lead.partner_id, existing)
        self.assertEqual(self.env['res.partner'].search_count([('email_normalized', '=', 'eleanor@sunrise.test'),
                                                               ('is_restaurant', '=', False)]), 1)

    def test_never_assigns_a_restaurant_as_client(self):
        # El restaurante comparte email con el remitente: no puede acabar como cliente.
        lead = self._email_lead()
        search = self._chosen_search(lead)
        search.action_create_sale_order()
        self.assertNotEqual(lead.partner_id, self.restaurant)
        self.assertFalse(lead.partner_id.is_restaurant)

    def test_uses_name_when_sender_has_no_display_name(self):
        lead = self._email_lead(email_from='nuevo.cliente@agencia.test')
        lead._restagrup_ensure_billing_partner()
        self.assertEqual(lead.partner_id.email, 'nuevo.cliente@agencia.test')
        self.assertTrue(lead.partner_id.name)

    def test_without_email_still_asks_for_contact(self):
        lead = self.env['crm.lead'].create({'name': 'Sin cliente ni email'})
        search = self._chosen_search(lead)
        with self.assertRaises(UserError):
            search.action_create_sale_order()
        self.assertFalse(lead.partner_id)

    def test_keeps_existing_partner(self):
        client = self.env['res.partner'].create({'name': 'Cliente Previo', 'email': 'otro@x.test'})
        lead = self._email_lead(partner_id=client.id)
        lead._restagrup_ensure_billing_partner()
        self.assertEqual(lead.partner_id, client)

    def test_salesman_without_purchase_rights_can_create_the_order(self):
        salesman = self.env['res.users'].create({
            'name': 'Comercial Test', 'login': 'comercial_billing_test', 'email': 'comercial@restagrup.test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        lead = self._email_lead(user_id=salesman.id)
        search = self._chosen_search(lead)
        search.with_user(salesman).action_create_sale_order()
        self.assertEqual(lead.partner_id.email, 'eleanor@sunrise.test')
        self.assertTrue(search.sale_order_id)
