# -*- coding: utf-8 -*-
"""Si a la agencia le falta el CIF o la razón social, al firmar el presupuesto se prepara un correo pidiéndoselos
(con lo que ya tenemos, para que lo revise), por la cola de aprobación (PPT de Conchita 2026-11-04, diap. 2)."""
from odoo.tests.common import TransactionCase, tagged

KIND = 'agency_fiscal_request'


@tagged('post_install', '-at_install')
class TestAgencyFiscalData(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.product = cls.env.ref('restagrup_service_orders.product_restaurant_service')

    def _group(self, **agency_vals):
        agency = self.env['res.partner'].create(dict({
            'name': 'Agencia Clandestina', 'is_company': True, 'email': 'reservas@clandestina.example.com',
            'street': 'Calle Larios 5', 'city': 'Málaga'}, **agency_vals))
        contact = self.env['res.partner'].create({
            'name': 'Erika Zarandona', 'parent_id': agency.id, 'email': 'erika@clandestina.example.com'})
        lead = self.env['crm.lead'].create({
            'name': 'Colegio Teresianas', 'partner_id': contact.id, 'email_from': contact.email})
        return agency, lead

    def _sign(self, lead):
        order = self.env['sale.order'].create({
            'partner_id': lead.partner_id.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 30, 'price_unit': 25})]})
        order.action_confirm()
        return order

    def _requests(self, lead):
        return self.env['restagrup.pending.mail'].search([('kind', '=', KIND), ('request_lead_id', '=', lead.id)])

    def test_missing_vat_and_legal_name_are_asked_for(self):
        agency, lead = self._group()
        self._sign(lead)
        mail = self._requests(lead)
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.state, 'pending', 'pasa por la cola de aprobación')
        self.assertIn('CIF', mail.body)
        self.assertIn('Razón social', mail.body)
        self.assertIn('Calle Larios 5', mail.body, 'con lo que ya tenemos, para que lo revise')
        self.assertIn(lead._restagrup_locator(), mail.subject)

    def test_nothing_is_asked_when_the_data_is_complete(self):
        _agency, lead = self._group(vat='ESB12345674', restagrup_legal_name='Clandestina Viajes S.L.')
        self._sign(lead)
        self.assertFalse(self._requests(lead))

    def test_only_what_is_missing_is_asked(self):
        _agency, lead = self._group(restagrup_legal_name='Clandestina Viajes S.L.')
        self._sign(lead)
        body = self._requests(lead).body
        self.assertIn('CIF', body)
        self.assertIn('Clandestina Viajes S.L.', body)

    def test_asked_only_once_per_agency(self):
        agency, lead = self._group()
        self._sign(lead)
        self._sign(lead)
        other_lead = self.env['crm.lead'].create({
            'name': 'Otro grupo', 'partner_id': lead.partner_id.id, 'email_from': lead.email_from})
        self._sign(other_lead)
        self.assertEqual(self.env['restagrup.pending.mail'].search_count([
            ('kind', '=', KIND), ('state', '=', 'pending'),
            ('request_lead_id', 'in', (lead | other_lead).ids)]), 1)

    def test_private_customers_are_not_asked(self):
        person = self.env['res.partner'].create({'name': 'Luis Pérez', 'email': 'luis@example.com'})
        lead = self.env['crm.lead'].create({'name': 'Cumpleaños', 'partner_id': person.id})
        self._sign(lead)
        self.assertFalse(self._requests(lead))

    def test_no_longer_asked_once_completed(self):
        agency, lead = self._group()
        self._sign(lead)
        mail = self._requests(lead)
        agency.write({'vat': 'ESB12345674', 'restagrup_legal_name': 'Clandestina Viajes S.L.'})
        mail.action_approve()
        self.assertEqual(mail.state, 'discarded')

    def test_approved_request_goes_out_on_the_group_thread(self):
        _agency, lead = self._group()
        self._sign(lead)
        mail = self._requests(lead)
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        self.assertTrue(lead.message_ids.filtered(lambda m: m.message_type == 'email' and m.subject == mail.subject))

    def test_legal_name_is_on_the_contact_form(self):
        arch = self.env['res.partner'].get_view(view_type='form')['arch']
        self.assertIn('name="restagrup_legal_name"', arch)
