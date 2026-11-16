# -*- coding: utf-8 -*-
from email.utils import parseaddr

from odoo.tests.common import TransactionCase, tagged

OUTBOX = 'salida@restagrup.example'


@tagged('post_install', '-at_install')
class TestSender1311(TransactionCase):
    """Reunión 13/11 (P14): los correos a agencias y restaurantes salían como «Ruben» <buzón de salida> (Odoo cambia
    la dirección por la del servidor pero deja el nombre del usuario). Deben salir del buzón de salida con el nombre
    «Restagrup · <usuario>»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env['ir.config_parameter'].sudo()
        cls.params.set_param('restagrup.system_sender', False)
        cls.params.set_param('restagrup.sender_name', False)
        cls.params.set_param('mail.default.from', OUTBOX)
        cls.env.company.alias_domain_id = False
        cls.user = cls.env['res.users'].create({
            'name': 'Ruben', 'login': 'ruben_1311', 'email': 'grupos1@restagrup.example',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('base.group_partner_manager').id])]})
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia', 'email': 'agencia@example.com'})

    class Session:
        """Como la sesión SMTP de prod: autenticada con el buzón de salida."""
        smtp_from = OUTBOX
        from_filter = OUTBOX

    def _send_headers(self, email_from):
        """(sobre, From) tal y como salen: construir el correo y prepararlo para la sesión SMTP. Lo segundo es lo
        que en prod dejaba el buzón sin nombre (llegaba como «Ruben»)."""
        Server = self.env['ir.mail_server']
        message = Server._build_email__(
            email_from=email_from, email_to=['agencia@example.com'], subject='Prueba', body='<p>Hola</p>',
            subtype='html')
        smtp_from, _to, message = Server._prepare_email_message__(message, self.Session())
        return smtp_from, parseaddr(message['From'])

    def _from_header(self, email_from):
        return self._send_headers(email_from)[1]

    def test_prod_session_without_matching_server(self):
        """Prod (16/11): ningún servidor casa con el correo del usuario, Odoo deja su From y su sobre, y Gmail
        cambiaba solo la dirección: llegaba «Ruben <buzón>». Debe salir del buzón con la marca."""
        class ProdSession:
            smtp_from = '"Ruben" <grupos1@restagrup.example>'
            from_filter = OUTBOX
        Server = self.env['ir.mail_server']
        message = Server._build_email__(
            email_from='"Ruben" <grupos1@restagrup.example>', email_to=['agencia@example.com'], subject='Prueba',
            body='<p>Hola</p>', subtype='html')
        smtp_from, _to, message = Server._prepare_email_message__(message, ProdSession())
        self.assertEqual(parseaddr(message['From']), ('Restagrup · Ruben', OUTBOX))
        self.assertEqual(smtp_from, OUTBOX)

    def test_envelope_stays_the_outbox(self):
        self.assertEqual(parseaddr(self._send_headers('"Ruben" <grupos1@restagrup.example>')[0])[1], OUTBOX)

    def test_external_sender_does_not_get_the_brand(self):
        name, address = self._from_header('"Agencia" <agencia@example.com>')
        self.assertEqual(address, OUTBOX)
        self.assertNotIn('Restagrup', name)

    def test_sender_address_is_the_outbox(self):
        self.assertEqual(self.env['restagrup.system.mail'].sender_address(), OUTBOX)

    def test_configured_system_sender_wins(self):
        self.params.set_param('restagrup.system_sender', 'reservas@restagrup.example')
        self.assertEqual(self.env['restagrup.system.mail'].sender_address(), 'reservas@restagrup.example')

    def test_user_mail_goes_out_from_the_outbox_with_brand_and_user(self):
        self.assertEqual(self._from_header('"Ruben" <grupos1@restagrup.example>'),
                         ('Restagrup · Ruben', OUTBOX))

    def test_bare_user_email_is_also_rewritten(self):
        self.assertEqual(self._from_header('grupos1@restagrup.example'), ('Restagrup · Ruben', OUTBOX))

    def test_brand_name_comes_from_settings(self):
        self.params.set_param('restagrup.sender_name', 'Restagrup Central de Reservas')
        self.assertEqual(self._from_header('grupos1@restagrup.example'),
                         ('Restagrup Central de Reservas · Ruben', OUTBOX))

    def test_outbox_sender_gets_the_brand(self):
        self.assertEqual(self._from_header(OUTBOX), ('Restagrup', OUTBOX))

    def test_external_sender_is_not_touched(self):
        self.assertEqual(self.env['restagrup.system.mail'].outgoing_from('"Agencia" <agencia@example.com>'),
                         '"Agencia" <agencia@example.com>')

    def test_without_outbox_nothing_changes(self):
        self.params.set_param('mail.default.from', False)
        self.env['ir.mail_server'].sudo().search([]).write({'active': False})
        self.assertEqual(self.env['restagrup.system.mail'].outgoing_from('grupos1@restagrup.example'),
                         'grupos1@restagrup.example')

    def test_message_post_to_agency_goes_out_from_the_outbox(self):
        message = self.agency.with_user(self.user).with_context(mail_notify_force_send=False).message_post(
            body='Hola', subject='Propuesta', message_type='email', subtype_xmlid='mail.mt_comment',
            outgoing_email_to='agencia@example.com')
        mails = self.env['mail.mail'].sudo().search([('mail_message_id', '=', message.id)])
        self.assertTrue(mails)
        # Odoo construye el correo con el email_from del mail.mail (en los tests no llega a conectar al SMTP).
        self.assertEqual({self._from_header(mail.email_from) for mail in mails}, {('Restagrup · Ruben', OUTBOX)})
        self.assertIn('grupos1@restagrup.example', message.email_from)  # el chatter sigue diciendo quién fue

