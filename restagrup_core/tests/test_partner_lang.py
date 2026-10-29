# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPartnerLang(TransactionCase):
    """Los contactos que crean el buzón y los crons (OdooBot, en inglés) nacen en español: si no, los correos
    estándar de Odoo (presupuesto, pedido) les salen en inglés."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('en_US')
        # Como en producción (base creada en inglés): sin idioma por defecto para los contactos.
        cls.env['ir.default'].search([('field_id.model', '=', 'res.partner'), ('field_id.name', '=', 'lang')]).unlink()
        cls.env['res.partner']._restagrup_set_default_lang()

    def test_contact_created_by_the_mail_gateway_is_in_spanish(self):
        partner = self.env['res.partner'].with_context(lang='en_US').create({'name': 'Agencia desde correo'})
        self.assertEqual(partner.lang, 'es_ES')

    def test_an_explicit_language_is_kept(self):
        partner = self.env['res.partner'].create({'name': 'Agency UK', 'lang': 'en_US'})
        self.assertEqual(partner.lang, 'en_US')

    def test_company_contact_default_is_spanish(self):
        self.assertEqual(self.env['res.partner'].default_get(['lang']).get('lang'), 'es_ES')

    def test_setting_the_default_twice_is_harmless(self):
        self.env['res.partner']._restagrup_set_default_lang()
        self.assertEqual(self.env['res.partner'].default_get(['lang']).get('lang'), 'es_ES')
