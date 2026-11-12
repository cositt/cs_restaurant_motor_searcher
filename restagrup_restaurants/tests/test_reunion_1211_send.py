# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

WIZARD = 'restagrup.send.wizard'


@tagged('post_install', '-at_install')
class TestReviewAndSend(TransactionCase):
    """Reunión 12/11: 4.1/7.6 (revisar y editar el correo antes de enviarlo a un restaurante) y 3.6/3.7 (elegir
    a quién de la compañía va: la ficha y/o sus contactos, aunque el email solo lo tenga un contacto)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Line = cls.env['restagrup.restaurant.search.line']
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo escolar 1211'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 42,
        })
        cls.ribs = cls.Partner.create({'name': 'Ribs Abada', 'is_restaurant': True, 'email': 'ribs@example.com'})
        cls.pedro = cls.Partner.create({'name': 'Pedro', 'parent_id': cls.ribs.id, 'email': 'pedro@example.com'})
        cls.admin = cls.Partner.create({'name': 'Administración', 'parent_id': cls.ribs.id,
                                        'email': 'admin@example.com'})

    def _line(self, partner, **vals):
        return self.Line.create(dict({
            'search_id': self.search.id, 'source': 'partner', 'name': partner.name, 'partner_id': partner.id,
            'etiqueta': 'interesado',
        }, **vals))

    def _wizard(self, action):
        self.assertEqual(action['res_model'], WIZARD)
        return self.env[WIZARD].browse(action['res_id'])

    def _sent(self, line):
        return line.message_ids.filtered(lambda m: m.message_type == 'email')

    # --- pedir presupuesto ---

    def test_request_quote_opens_editable_window_without_sending(self):
        line = self._line(self.ribs)
        wizard = self._wizard(line.action_open_quote_request())
        self.assertIn('Presupuesto', wizard.subject)
        self.assertTrue(wizard.body)
        self.assertEqual(wizard.recipient_ids, self.ribs)
        self.assertEqual(wizard.candidate_ids, self.ribs | self.pedro | self.admin)
        self.assertFalse(self._sent(line), 'abrir la ventana no envía nada')
        self.assertEqual(line.etiqueta, 'interesado')

    def test_edited_text_is_what_the_restaurant_receives(self):
        line = self._line(self.ribs)
        wizard = self._wizard(line.action_open_quote_request())
        wizard.write({'subject': 'Plato combinado para 42', 'body': 'Hola,\nno queremos menú, plato combinado.'})
        wizard.action_send()
        message = self._sent(line)
        self.assertEqual(len(message), 1)
        self.assertIn('no queremos menú, plato combinado', message.body)
        self.assertTrue(message.subject.startswith('Plato combinado para 42'))
        self.assertEqual(line.etiqueta, 'solicitado')

    def test_can_send_to_several_people_of_the_restaurant(self):
        line = self._line(self.ribs)
        wizard = self._wizard(line.action_open_quote_request())
        wizard.write({'recipient_ids': [(6, 0, (self.ribs | self.pedro).ids)], 'extra_emails': 'otro@example.com'})
        wizard.action_send()
        sent_to = self._sent(line).outgoing_email_to
        for email in ('ribs@example.com', 'pedro@example.com', 'otro@example.com'):
            self.assertIn(email, sent_to)
        self.assertNotIn('admin@example.com', sent_to)

    def test_without_recipients_it_does_not_send(self):
        line = self._line(self.ribs)
        wizard = self._wizard(line.action_open_quote_request())
        wizard.recipient_ids = False
        with self.assertRaises(UserError):
            wizard.action_send()

    # --- 3.6: el email solo lo tiene un contacto ---

    def test_contact_email_is_used_when_the_restaurant_has_none(self):
        restaurant = self.Partner.create({'name': 'Sin Email', 'is_restaurant': True})
        contact = self.Partner.create({'name': 'Gerente', 'parent_id': restaurant.id, 'email': 'gerente@example.com'})
        line = self._line(restaurant)
        self.assertEqual(line._get_quote_email_to(), 'gerente@example.com')
        wizard = self._wizard(line.action_open_quote_request())
        self.assertEqual(wizard.recipient_ids, contact)

    # --- a todos los interesados: un texto común ---

    def test_request_to_interested_uses_one_common_text(self):
        first = self._line(self.ribs)
        other = self.Partner.create({'name': 'La Musa', 'is_restaurant': True, 'email': 'musa@example.com'})
        second = self._line(other)
        wizard = self._wizard(self.search.action_request_quote_interested())
        self.assertIn('Ribs Abada', wizard.recipients_summary)
        self.assertIn('La Musa', wizard.recipients_summary)
        self.assertFalse(self._sent(first) | self._sent(second))
        wizard.body = 'Hola {restaurante},\n' + wizard.body + '\nTexto común añadido.'
        wizard.action_send()
        for line, name in ((first, 'Ribs Abada'), (second, 'La Musa')):
            message = self._sent(line)
            self.assertEqual(len(message), 1)
            self.assertIn('Texto común añadido.', message.body)
            self.assertNotIn('{restaurante}', message.body)
            self.assertEqual(line.etiqueta, 'solicitado')
        self.assertIn('Hola La Musa', self._sent(second).body)
        self.assertIn('Hola Ribs Abada', self._sent(first).body)
        self.assertEqual(self._sent(second).outgoing_email_to, 'musa@example.com')
