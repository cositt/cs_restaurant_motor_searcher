# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestG2Reunion1211(TransactionCase):
    """Reunión 12/11, bloque G2: 8.2 nombre del menú siempre con año, 6.4 no pedir postre en platos combinados,
    5.1 «Registrar menú» / «Confirmar menú»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa G2', 'is_restaurant': True, 'email': 'casa-g2@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo G2 menús'})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 30, 'event_date': '2027-03-10', 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Madrid', 'min_capacity': 30})

    def _line(self):
        return self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'email': self.restaurant.email, 'etiqueta': 'solicitado'})

    def _reply(self, line, menus):
        with patch(LLM_PATH, return_value=({'importe': None, 'notas': None, 'menus': menus}, 'groq')):
            line.message_update({'body': '<p>Os mandamos el menú.</p>'})

    def _pending_text(self):
        mails = self.env['restagrup.pending.mail'].search([('search_id', '=', self.search.id)])
        return '\n'.join(mails.mapped('body'))

    # --- 8.2 ---
    def test_menu_without_year_gets_the_season(self):
        menu = self.Menu.create({'name': 'Menú grupos lunes a viernes', 'partner_id': self.restaurant.id,
                                 'season': 2027})
        self.assertEqual(menu.name, 'Menú grupos lunes a viernes 2027')

    def test_menu_with_year_is_not_touched(self):
        menu = self.Menu.create({'name': 'Menú escolar 2026', 'partner_id': self.restaurant.id, 'season': 2027})
        self.assertEqual(menu.name, 'Menú escolar 2026')

    def test_renaming_without_year_adds_it(self):
        menu = self.Menu.create({'name': 'Menú 2027', 'partner_id': self.restaurant.id, 'season': 2027})
        menu.name = 'Menú fin de semana'
        self.assertEqual(menu.name, 'Menú fin de semana 2027')

    def test_menu_from_reply_takes_the_year_of_the_service(self):
        self._reply(self._line(), [{'nombre': None, 'precio_persona': 25, 'bebidas': 'agua', 'platos': [
            {'tipo': 'principal', 'nombre': 'Pollo'}, {'tipo': 'postre', 'nombre': 'Flan'}]}])
        menu = self.Menu.search([('partner_id', '=', self.restaurant.id)])
        self.assertEqual(menu.season, 2027)
        self.assertEqual(menu.name, 'Menú grupos 2027')

    def test_existing_menus_without_year_are_renamed_once(self):
        old = self.Menu.create({'name': 'Menú antiguo', 'partner_id': self.restaurant.id, 'season': 2026})
        self.env.cr.execute('UPDATE restagrup_restaurant_menu SET name = %s WHERE id = %s', ('Menú antiguo', old.id))
        dated = self.Menu.create({'name': 'Menú escolar 2025', 'partner_id': self.restaurant.id, 'season': 2026})
        self.Menu.invalidate_model(['name'])
        self.assertEqual(old.name, 'Menú antiguo')
        self.Menu._restagrup_add_season_to_names()
        self.assertEqual(old.name, 'Menú antiguo 2026')
        self.assertEqual(dated.name, 'Menú escolar 2025')

    # --- 6.4 ---
    def test_combined_plate_menu_does_not_ask_for_dessert(self):
        self._reply(self._line(), [{'nombre': 'Plato combinado 2027', 'precio_persona': 12, 'bebidas': 'agua',
                                    'platos': [{'tipo': 'principal', 'nombre': 'Huevos, patatas y lomo'}]}])
        self.assertNotIn('Postre', self._pending_text())

    def test_full_menu_without_dessert_still_asks(self):
        self._reply(self._line(), [{'nombre': 'Menú del día 2027', 'precio_persona': 12, 'bebidas': 'agua',
                                    'platos': [{'tipo': 'principal', 'nombre': 'Lomo'}]}])
        self.assertIn('Postre', self._pending_text())

    # --- 5.1 ---
    def test_buttons_say_menu(self):
        arch = self.env['restagrup.restaurant.search'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('Registrar menú', arch)
        self.assertNotIn('Registrar presupuesto', arch)
        self.assertIn('string="Confirmar menú"', arch)
        self.assertIn('>Confirmar menú</button>', arch)
        self.assertNotIn('Confirmar presupuesto', arch)
        quote_form = self.env.ref('restagrup_restaurants.view_restaurant_search_line_quote_form')
        self.assertIn('Registrar menú', quote_form.arch)
