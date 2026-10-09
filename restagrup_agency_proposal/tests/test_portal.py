# -*- coding: utf-8 -*-
import re

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestComparisonPortal(HttpCase):
    """Página pública de la comparativa: se ve con el token y el cliente elige restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo Whitfield', 'email_from': 'cliente@example.com'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 40,
        })
        cls.line_a = cls._quote('Asador Azul', 1000.0, 'Gazpachuelo malagueño')
        cls.line_b = cls._quote('Casa Cara', 2000.0, 'Cordero lechal')
        cls.pending = cls._quote('Mesón Pendiente', 500.0, 'Plato secreto', etiqueta='solicitado')
        cls.url = cls.search._comparison_portal_url().split('://', 1)[1].split('/', 1)[1]
        cls.url = '/' + cls.url

    @classmethod
    def _quote(cls, name, amount, dish, etiqueta='presupuesto_recibido'):
        partner = cls.env['res.partner'].create({'name': name, 'is_restaurant': True})
        menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú de grupo', 'partner_id': partner.id, 'cost_price': 31.77,
            'line_ids': [(0, 0, {'course': 'principal', 'name': dish})],
        })
        return cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': name, 'partner_id': partner.id,
            'etiqueta': etiqueta, 'quote_amount': amount, 'menu_id': menu.id,
        })

    def _choose(self, line, url=None):
        return self.url_open('%s/elegir' % (url or self.url), data={'line_id': line.id})

    def test_page_shows_confirmed_restaurants_with_menu(self):
        response = self.url_open(self.url)
        self.assertEqual(response.status_code, 200)
        for text in ('Asador Azul', 'Gazpachuelo malagueño', 'Casa Cara', 'Cordero lechal'):
            self.assertIn(text, response.text)

    def test_page_hides_unconfirmed_quotes_and_restaurant_costs(self):
        text = re.sub(r'<[^>]+>', ' ', self.url_open(self.url).text)
        self.assertNotIn('Mesón Pendiente', text)
        self.assertNotIn('Plato secreto', text)
        self.assertRegex(text, r'30[.,]00')
        self.assertNotRegex(text, r'31[.,]77')
        self.assertNotRegex(text, r'(?<!\d)1[.,\s\xa0]?000[.,]00')

    def test_wrong_token_is_not_found(self):
        wrong = '/comparativa/%s/token-falso' % self.search.id
        self.assertEqual(self.url_open(wrong).status_code, 404)
        self.assertEqual(self._choose(self.line_a, wrong).status_code, 404)
        self.assertFalse(self.search.chosen_line_id)

    def test_search_without_token_is_not_found(self):
        other = self.env['restagrup.restaurant.search'].create({'lead_id': self.lead.id, 'city': 'Sevilla'})
        self.assertEqual(self.url_open('/comparativa/%s/False' % other.id).status_code, 404)

    def test_client_can_choose_a_restaurant(self):
        response = self._choose(self.line_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.search.chosen_line_id, self.line_a)
        self.assertIn('Asador Azul', response.text)
        note = self.lead.message_ids.filtered(lambda m: 'portal' in (m.body or '')).mapped('body')
        self.assertTrue(note)

    def test_client_cannot_choose_an_unconfirmed_restaurant(self):
        self._choose(self.pending)
        self.assertFalse(self.search.chosen_line_id)

    def test_client_cannot_override_an_existing_choice(self):
        self.search.chosen_line_id = self.line_a
        self._choose(self.line_b)
        self.assertEqual(self.search.chosen_line_id, self.line_a)

    def test_page_has_no_totals(self):
        text = re.sub(r'<[^>]+>', ' ', self.url_open(self.url).text)
        self.assertNotRegex(text, r'1[.,\s\xa0]?200[.,]00')
        self.assertNotIn('Total', text)

    def test_hidden_restaurant_page_shows_options_not_names(self):
        self.search.restaurant_visible = False
        response = self.url_open(self.url)
        self.assertNotIn('Asador Azul', response.text)
        self.assertNotIn('Casa Cara', response.text)
        self.assertIn('Opción 1', response.text)
        self.assertIn('Gazpachuelo malagueño', response.text)

    def test_hidden_restaurant_choice_banner_uses_the_option_label(self):
        self.search.restaurant_visible = False
        response = self._choose(self.line_a)
        self.assertEqual(self.search.chosen_line_id, self.line_a)
        self.assertNotIn('Asador Azul', response.text)
        self.assertIn('Opción 1', response.text)
