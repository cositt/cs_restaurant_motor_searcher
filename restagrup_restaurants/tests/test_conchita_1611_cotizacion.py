# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'
OLD_NAME = 'Precio de catálogo'
NEW_NAME = 'Cotización'


@tagged('post_install', '-at_install')
class TestConchita1611Cotizacion(TransactionCase):
    """Correo de Conchita 16/11 (1.2): el botón «Precio de catálogo» pasa a llamarse «Cotización»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Cotización', 'is_restaurant': True, 'is_company': True, 'city': 'Madrid'})
        Menu = cls.env['restagrup.restaurant.menu']
        Menu.create({'name': 'Menú A', 'partner_id': cls.restaurant.id, 'cost_price': 20})
        Menu.create({'name': 'Menú B', 'partner_id': cls.restaurant.id, 'cost_price': 25})
        lead = cls.env['crm.lead'].create({'name': 'Grupo cotización'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 30})
        cls.line = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'interesado'})

    def test_search_screen_buttons_are_called_cotizacion(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertNotIn(OLD_NAME, arch)
        self.assertGreaterEqual(arch.count('>%s<' % NEW_NAME) + arch.count('string="%s"' % NEW_NAME), 2)

    def test_window_to_pick_the_menu_is_called_cotizacion(self):
        action = self.line.action_quote_from_catalog()
        self.assertIn(NEW_NAME, action['name'])

    def test_chatter_note_names_the_new_button(self):
        self.line._apply_catalog_quote(self.env['restagrup.restaurant.menu'].search(
            [('partner_id', '=', self.restaurant.id)], limit=1))
        note = self.search.message_ids.sorted('id')[-1].body
        self.assertIn(NEW_NAME.lower(), note.lower())
