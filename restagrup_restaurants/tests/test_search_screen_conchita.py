# -*- coding: utf-8 -*-
"""Pantalla «Buscar restaurantes» más clara (PPT de Conchita 2026-11-04, diapositivas 3 y 5): volver a la
petición, Grupo separado de la agencia, buscar un restaurante por su nombre y estados que no retroceden."""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

GOOGLE_PATH = ('odoo.addons.restagrup_restaurants.models.restaurant_search.RestaurantSearch._search_google')


@tagged('post_install', '-at_install')
class TestSearchScreenConchita(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Teresianas'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 30})
        cls.fria = cls.env['res.partner'].create({
            'name': 'Restaurante La Fría', 'is_restaurant': True, 'city': 'Málaga', 'restaurant_capacity': 80})
        cls.other = cls.env['res.partner'].create({
            'name': 'Bodega El Pimpi', 'is_restaurant': True, 'city': 'Málaga', 'restaurant_capacity': 80})

    def _form_arch(self):
        return self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']

    def _line(self, etiqueta):
        return self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'partner', 'name': self.fria.name,
            'partner_id': self.fria.id, 'etiqueta': etiqueta})

    # --- 3.1 volver a la petición ---

    def test_back_to_petition_button(self):
        self.assertIn('name="action_open_lead"', self._form_arch())

    def test_back_to_petition_opens_the_lead(self):
        action = self.search.action_open_lead()
        self.assertEqual((action['res_model'], action['res_id']), ('crm.lead', self.lead.id))

    # --- 3.2 Grupo y agencia separados ---

    def test_lead_is_labelled_group(self):
        self.assertEqual(self.search._fields['lead_id'].string, 'Grupo')

    # --- 3.5 el elegido no parece un filtro; buscar por nombre ---

    def test_chosen_restaurant_is_not_an_editable_field(self):
        arch = self._form_arch()
        chosen = arch.split('name="chosen_line_id"')[1].split('/>')[0]
        self.assertIn('readonly="1"', chosen)
        self.assertIn('invisible="not chosen_line_id"', chosen)

    def test_search_by_restaurant_name(self):
        self.search.restaurant_name = 'fría'
        with patch(GOOGLE_PATH, return_value=[]):
            self.search.action_search()
        self.assertEqual(self.search.line_ids.partner_id, self.fria)

    def test_name_goes_to_google_as_keyword(self):
        self.search.restaurant_name = 'La Fría'
        _url, params = self.search._build_google_search_params('k', (36.7, -4.4), 'restaurant', 'restaurantes')
        self.assertIn('La Fría', params['keyword'])
        _url, params = self.search._build_google_search_params('k', None, 'restaurant', 'restaurantes')
        self.assertIn('La Fría', params['query'])

    # --- 5.2 los estados no retroceden ---

    def test_interested_does_not_undo_a_received_quote(self):
        line = self._line('presupuesto_recibido')
        line.action_mark_interesado()
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')

    def test_interested_does_not_undo_a_requested_quote(self):
        line = self._line('solicitado')
        line.action_mark_interesado()
        self.assertEqual(line.etiqueta, 'solicitado')

    def test_interested_button_hidden_once_requested(self):
        card = self._form_arch().split('<t t-name="card">')[1]
        button = card.split('name="action_mark_interesado"')[0].rsplit('<button', 1)[1]
        self.assertIn("'solicitado'", button)
        self.assertIn("'presupuesto_recibido'", button)

    def test_card_shows_the_stage_steps(self):
        self.assertIn('o_restagrup_steps', self._form_arch())

    # --- 3.3 arriba lo básico; el resto, en «Filtros» plegable ---

    def test_filters_are_folded_away(self):
        arch = self._form_arch()
        folded = arch.split('<details')[1].split('</details>')[0]
        for name in ('street', 'zip', 'require_bus_parking', 'cuisine_type', 'max_price_level',
                     'search_type_restaurant'):
            self.assertIn('name="%s"' % name, folded, name)
        top = arch.split('<details')[0]
        for name in ('lead_id', 'event_id', 'city', 'min_capacity'):
            self.assertIn('name="%s"' % name, top, name)

    # --- 4.3 un único sitio para pegar la respuesta del restaurante ---

    def test_quote_form_has_one_place_to_paste(self):
        view = self.env.ref('restagrup_restaurants.view_restaurant_search_line_quote_form')
        arch = self.env['restagrup.restaurant.search.line'].get_view(view_id=view.id)['arch']
        self.assertEqual(arch.count('name="quote_raw_text"'), 1)
        self.assertIn('Leer con IA: precio y menú', arch)
        self.assertIn('1. Pega la respuesta del restaurante', arch)

    def test_card_button_says_paste_reply(self):
        card = self._form_arch().split('<t t-name="card">')[1]
        self.assertIn("Registrar menú", card)  # reunión 12/11 (5.1)
