# -*- coding: utf-8 -*-
from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReunion1211Restaurants(TransactionCase):
    """Reunión 12/11: 5.2 (contacto ya existente sin marcar como restaurante) y 4.7 («Pedir datos que faltan»
    pulsado sin querer y enviado a un email que ya no es el del restaurante)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Line = cls.env['restagrup.restaurant.search.line']
        cls.Pending = cls.env['restagrup.pending.mail']
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo escolar 1211'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 42,
        })

    # --- 5.2 ---

    def test_adding_existing_contact_marks_it_as_restaurant(self):
        existing = self.Partner.create({'name': 'Ribs Abada', 'restaurant_google_place_id': 'PLACE-RIBS'})
        self.assertFalse(existing.is_restaurant)
        line = self.Line.create({
            'search_id': self.search.id, 'source': 'google', 'name': 'RIBS ABADA', 'google_place_id': 'PLACE-RIBS',
            'phone': '910000000',
        })
        line.action_add_as_partner()
        self.assertEqual(line.partner_id, existing)
        self.assertTrue(existing.is_restaurant)

    # --- 4.7 ---

    def _incomplete_line(self):
        partner = self.Partner.create({'name': 'Casa Botín', 'is_restaurant': True, 'email': 'reservas@botin.example'})
        return self.Line.create({
            'search_id': self.search.id, 'source': 'partner', 'name': partner.name, 'partner_id': partner.id,
            'email': partner.email,
        })

    def test_request_missing_data_button_asks_for_confirmation(self):
        arch = self.env['restagrup.restaurant.search'].get_views([(False, 'form')])['views']['form']['arch']
        buttons = etree.fromstring(arch).xpath("//button[@name='action_request_missing_data']")
        self.assertTrue(buttons)
        self.assertTrue(all(button.get('confirm') for button in buttons))

    def test_data_request_reason_says_who_asked_and_for_which_group(self):
        line = self._incomplete_line()
        line.action_request_missing_data()
        mail = self.Pending.search([('line_id', '=', line.id), ('kind', '=', 'data_request')])
        self.assertIn(self.env.user.name, mail.reason)
        self.assertIn('Grupo escolar 1211', mail.reason)

    def test_queue_warns_when_restaurant_email_changed_after_queueing(self):
        line = self._incomplete_line()
        line.action_request_missing_data()
        mail = self.Pending.search([('line_id', '=', line.id), ('kind', '=', 'data_request')])
        self.assertFalse(mail.recipient_warning)
        line.partner_id.email = 'nuevo@botin.example'
        mail.invalidate_recordset(['recipient_warning'])
        self.assertIn('nuevo@botin.example', mail.recipient_warning)
