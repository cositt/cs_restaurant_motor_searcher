# -*- coding: utf-8 -*-
"""Restagrup trabaja siempre por precio de menú por persona, nunca por total del grupo
(ticket de Conchita 2026-11-04: registró 19 € y la app lo tomó como total → 0,76 €/pax)."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestQuotePerPerson(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante Precio', 'is_restaurant': True, 'email': 'precio@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo precio por persona'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 30})

    def _line(self, **vals):
        return self.env['restagrup.restaurant.search.line'].create(dict({
            'search_id': self.search.id, 'source': 'partner', 'name': 'Restaurante Precio',
            'partner_id': self.restaurant.id, 'email': 'precio@example.com', 'etiqueta': 'solicitado',
        }, **vals))

    # --- el precio que se escribe es por persona ---

    def test_price_per_person_gives_group_total(self):
        line = self._line(quote_price_pp=19.0)
        self.assertEqual(line.quote_price_pp, 19.0)
        self.assertAlmostEqual(line.quote_amount, 570.0, msg='30 pax × 19 €')

    def test_registering_per_person_price_keeps_it_per_person(self):
        line = self._line()
        line.quote_price_pp = 19.0
        line.action_register_quote()
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')
        self.assertEqual(line.quote_price_pp, 19.0, 'nunca se divide otra vez entre los comensales')
        self.assertAlmostEqual(line.quote_amount, 570.0)

    def test_register_without_price_is_refused(self):
        line = self._line()
        with self.assertRaises(UserError):
            line.action_register_quote()

    def test_total_written_by_code_is_split_per_person(self):
        """Compatibilidad: el código que aún escribe el total (correos, demos) lo reparte por persona."""
        line = self._line(quote_amount=600.0)
        self.assertAlmostEqual(line.quote_price_pp, 20.0)
        self.assertAlmostEqual(line.quote_amount, 600.0)

    def test_total_follows_the_number_of_guests(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Málaga', 'min_capacity': 30})
        line = self._line(search_id=search.id, quote_price_pp=19.0)
        search.min_capacity = 40
        self.assertAlmostEqual(line.quote_amount, 760.0, msg='el precio por persona no cambia; el total sí')

    def test_without_guests_the_total_is_the_price(self):
        search = self.env['restagrup.restaurant.search'].create({'lead_id': self.lead.id, 'city': 'Málaga'})
        line = self._line(search_id=search.id, quote_price_pp=19.0)
        self.assertAlmostEqual(line.quote_amount, 19.0)

    # --- la IA lee el precio por persona ---

    def _paste(self, line, data):
        line.quote_raw_text = 'MENÚ GRUPOS\nPrimero a elegir...\nPRECIO POR PERSONA 19€'
        with patch(LLM_PATH, return_value=(dict({'notas': None, 'menus': []}, **data), 'groq')):
            line.action_extract_quote_from_text()

    def test_pasted_reply_with_only_per_person_price(self):
        line = self._line()
        self._paste(line, {'importe': None, 'precio_persona': 19})
        self.assertEqual(line.quote_price_pp, 19.0)
        self.assertAlmostEqual(line.quote_amount, 570.0)

    def test_pasted_reply_with_a_single_menu_price(self):
        line = self._line()
        self._paste(line, {'importe': None, 'menus': [{'nombre': 'Menú grupos', 'precio_persona': 19}]})
        self.assertEqual(line.quote_price_pp, 19.0, 'un solo menú con precio: ese es el precio por persona')

    def test_pasted_reply_with_only_a_total(self):
        line = self._line()
        self._paste(line, {'importe': 735.0})
        self.assertAlmostEqual(line.quote_price_pp, 24.5)

    def test_pasted_reply_without_any_price_still_fails(self):
        line = self._line()
        with self.assertRaises(UserError):
            self._paste(line, {'importe': None, 'menus': [
                {'nombre': 'A', 'precio_persona': 19}, {'nombre': 'B', 'precio_persona': 25}]})

    def test_emailed_reply_with_only_per_person_price(self):
        line = self._line()
        with patch(LLM_PATH, return_value=(
                {'importe': None, 'precio_persona': 19, 'notas': None, 'menus': []}, 'groq')):
            line.message_update({'body': '<p>Menú de grupo a 19 € por persona.</p>', 'attachments': []})
        self.assertEqual(line.quote_price_pp, 19.0)
        self.assertTrue(line.quote_pending_confirmation, 'sigue a la espera de que una persona lo registre')

    def test_prompt_asks_for_price_per_person(self):
        from odoo.addons.restagrup_restaurants.models.restaurant_search import EXTRACT_QUOTE_SYSTEM_PROMPT
        self.assertIn('"precio_persona"', EXTRACT_QUOTE_SYSTEM_PROMPT.split('"menus"')[0])

    # --- en la tarjeta: precio de venta por persona (con la comisión) ---

    def test_client_price_per_person_includes_commission(self):
        line = self._line(quote_price_pp=19.0)
        self.assertAlmostEqual(line.quote_client_price_per_person, 22.8, msg='19 € + 20 % de margen por defecto')

    def test_card_shows_sale_price_per_person(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        card = arch.split('<t t-name="card">')[1].split('</templates>')[0]
        self.assertIn('record.quote_client_price_per_person', card, 'la tarjeta enseña el precio con comisión')
        self.assertIn('record.quote_price_pp', card, 'y, pequeño, el coste por persona del restaurante')

    def test_register_dialog_asks_for_price_per_person(self):
        view = self.env.ref('restagrup_restaurants.view_restaurant_search_line_quote_form')
        arch = self.env['restagrup.restaurant.search.line'].get_view(view_id=view.id)['arch']
        self.assertIn('name="quote_price_pp"', arch)
        total = arch.split('name="quote_amount"')[1].split('/>')[0]
        self.assertIn('readonly="1"', total, 'el total del grupo se calcula, no se escribe')
