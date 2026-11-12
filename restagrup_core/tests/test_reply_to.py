# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

REPLIES_MODEL = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestRepliesComeBackToOdoo(TransactionCase):
    """Reunión 12/11 (4.3/4.4): los correos salían con «responder a» = email del agente (grupos1@), así que la
    respuesta del restaurante iba a su buzón y no entraba en Odoo. Ahora «responder a» es el buzón que lee Odoo y
    la respuesta vuelve al hilo del que salió (por References)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env['ir.config_parameter'].sudo()
        cls.params.set_param('restagrup.reply_to', False)
        cls.env['fetchmail.server'].sudo().search([]).write({'active': False})
        cls.env.company.alias_domain_id = False
        cls.partner = cls.env['res.partner'].create({'name': 'Ribs Abada', 'email': 'ribs@example.com'})

    def _reply_to(self, record):
        return record._notify_get_reply_to(default='grupos1@restagrup.example')[record.id or False]

    def test_without_mailbox_it_stays_as_odoo_does(self):
        self.assertEqual(self._reply_to(self.partner), 'grupos1@restagrup.example')

    def test_configured_mailbox_is_the_reply_to(self):
        self.params.set_param('restagrup.reply_to', ' respuestas@restagrup.example ')
        self.assertIn('respuestas@restagrup.example', self._reply_to(self.partner))

    def test_falls_back_to_the_mailbox_that_reads_restaurant_replies(self):
        model = self.env['ir.model']._get(REPLIES_MODEL) or self.env['ir.model']._get('res.partner')
        self.env['fetchmail.server'].sudo().create({
            'name': 'Respuestas', 'server': 'imap.example.com', 'server_type': 'imap', 'user': 'buzon@example.com',
            'password': 'x', 'object_id': model.id})
        if model.model == REPLIES_MODEL:
            self.assertIn('buzon@example.com', self._reply_to(self.partner))

    def test_message_post_uses_it(self):
        self.params.set_param('restagrup.reply_to', 'respuestas@restagrup.example')
        message = self.partner.message_post(
            body='Hola', subject='Presupuesto', message_type='email', email_from='grupos1@restagrup.example',
            outgoing_email_to='ribs@example.com')
        self.assertIn('respuestas@restagrup.example', message.reply_to)

    def test_a_real_alias_domain_still_wins(self):
        self.params.set_param('restagrup.reply_to', 'respuestas@restagrup.example')
        self.env.company.alias_domain_id = self.env['mail.alias.domain'].create({
            'name': 'restagrup.example', 'catchall_alias': 'catchall'})
        self.assertIn('catchall@restagrup.example', self._reply_to(self.partner))
