# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.tests.common import TransactionCase, tagged

THIS_YEAR = date.today().year
LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
WIZARD = 'restagrup.menu.duplicate.wizard'

DISHES = [
    {'tipo': 'entrante', 'nombre': 'Ensalada mixta'},
    {'tipo': 'entrante', 'nombre': 'Migas rondeñas'},
    {'tipo': 'principal', 'nombre': 'Carrillada a la rondeña'},
    {'tipo': 'postre', 'nombre': 'Postre casero'},
]


def _menu(name='Menú de paso', price=17.6, dishes=DISHES):
    return {'nombre': name, 'tipo': 'almuerzo', 'precio_persona': price, 'bebidas': 'Agua y vino',
            'platos': list(dishes), 'min_comensales': 20, 'max_comensales': 60}


@tagged('post_install', '-at_install')
class TestMenuDuplicateWarning(TransactionCase):
    """Reunión 23/11: al leer una respuesta con IA, si ya hay un menú igual o casi igual en la ficha del restaurante
    se avisa ANTES de crear otro, y se elige entre usar el que hay o crear uno nuevo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa Duplicados', 'is_restaurant': True, 'email': 'dup@example.com'})
        cls.other = cls.env['res.partner'].create({
            'name': 'Otra Casa', 'is_restaurant': True, 'email': 'otra@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo duplicados'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Ronda', 'min_capacity': 48})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': 'Casa Duplicados',
            'partner_id': cls.restaurant.id, 'email': 'dup@example.com', 'etiqueta': 'solicitado',
            'quote_raw_text': 'Menú de paso a 17,60 con ensalada, migas, carrillada y postre.'})

    def _existing(self, partner=None, **kwargs):
        vals = {'name': 'Menú de paso', 'partner_id': (partner or self.restaurant).id, 'cost_price': 17.6,
                'line_ids': [(0, 0, {'course': d['tipo'], 'name': d['nombre']}) for d in DISHES]}
        vals.update(kwargs)
        return self.Menu.create(vals)

    def _extract(self, menu, importe=845.0):
        with patch(LLM_PATH, return_value=({'importe': importe, 'notas': None, 'menus': [menu]}, 'groq')):
            return self.line.action_extract_quote_from_text()

    def _menus(self):
        return self.Menu.search([('partner_id', '=', self.restaurant.id)])

    # --- aviso antes de crear ---

    def test_identical_menu_warns_before_creating(self):
        existing = self._existing()
        action = self._extract(_menu())
        self.assertEqual(action['res_model'], WIZARD)
        self.assertEqual(self._menus(), existing, 'no se crea nada hasta que se elija')
        wizard = self.env[WIZARD].browse(action['res_id'])
        self.assertIn(existing.name, wizard.summary)
        self.assertFalse(wizard.can_create_new, 'si es idéntico, crear otro no tiene sentido')

    def test_almost_identical_menu_warns_and_allows_a_new_one(self):
        existing = self._existing()
        changed = _menu(price=19.5, dishes=DISHES[:3] + [{'tipo': 'postre', 'nombre': 'Tarta de queso'}])
        action = self._extract(changed, importe=936.0)
        self.assertEqual(action['res_model'], WIZARD)
        wizard = self.env[WIZARD].browse(action['res_id'])
        self.assertTrue(wizard.can_create_new)
        self.assertIn('19', wizard.summary, 'se ve en qué se parecen y en qué cambia el precio')
        self.assertEqual(self._menus(), existing)

    def test_same_name_with_other_dishes_warns(self):
        self._existing()
        other_dishes = [{'tipo': 'principal', 'nombre': 'Rabo de toro'}, {'tipo': 'postre', 'nombre': 'Flan'}]
        action = self._extract(_menu(price=22.0, dishes=other_dishes), importe=1056.0)
        self.assertEqual(action['res_model'], WIZARD)

    def test_unrelated_menu_is_created_without_warning(self):
        self._existing()
        different = _menu(name='Menú degustación', price=40.0,
                          dishes=[{'tipo': 'principal', 'nombre': 'Cochinillo'}, {'tipo': 'postre', 'nombre': 'Helado'}])
        action = self._extract(different, importe=1920.0)
        self.assertEqual(action['res_model'], 'restagrup.restaurant.search.line')
        self.assertEqual(len(self._menus()), 2)

    def test_first_menu_of_the_restaurant_is_created_without_warning(self):
        action = self._extract(_menu())
        self.assertEqual(action['res_model'], 'restagrup.restaurant.search.line')
        self.assertEqual(len(self._menus()), 1)

    def test_menus_of_other_restaurants_do_not_count(self):
        self._existing(partner=self.other)
        action = self._extract(_menu())
        self.assertEqual(action['res_model'], 'restagrup.restaurant.search.line')
        self.assertEqual(len(self._menus()), 1)

    # --- la elección ---

    def test_use_existing_assigns_it_and_creates_nothing(self):
        existing = self._existing()
        wizard = self.env[WIZARD].browse(self._extract(_menu(price=19.5))['res_id'])
        action = wizard.action_use_existing()
        self.assertEqual(self.line.menu_id, existing)
        self.assertEqual(self._menus(), existing)
        self.assertEqual(action['res_model'], 'restagrup.restaurant.search.line')
        self.assertEqual(action['res_id'], self.line.id)

    def test_create_new_creates_it_linked_to_the_similar_one(self):
        existing = self._existing()
        wizard = self.env[WIZARD].browse(self._extract(_menu(price=19.5))['res_id'])
        wizard.action_create_new()
        new = self._menus() - existing
        self.assertEqual(len(new), 1)
        self.assertEqual(new.similar_menu_id, existing)
        self.assertEqual(new.cost_price, 19.5)
        self.assertEqual(self.line.menu_id, new)

    def test_cancel_leaves_the_price_registered_but_no_menu(self):
        self._existing()
        wizard = self.env[WIZARD].browse(self._extract(_menu(price=19.5))['res_id'])
        self.assertFalse(self.line.menu_id)
        self.assertTrue(self.line.quote_price_pp, 'el precio extraído ya se propuso')
        self.assertEqual(wizard.action_cancel(), {'type': 'ir.actions.act_window_close'})

    def test_email_replies_keep_creating_the_menu_on_their_own(self):
        """Por correo no hay nadie delante a quien preguntar: sigue el comportamiento de siempre."""
        existing = self._existing()
        line = self.line.copy({'etiqueta': 'solicitado'})
        with patch(LLM_PATH, return_value=({'importe': 936.0, 'notas': None, 'menus': [_menu(price=19.5)]}, 'groq')):
            line.message_update({'body': '<p>Menú.</p>', 'attachments': []})
        self.assertEqual(len(self._menus()), 2)
        self.assertTrue((self._menus() - existing).similar_menu_id)


@tagged('post_install', '-at_install')
class TestMenuNameInQuoteForm(TransactionCase):
    """Reunión 23/11 («el nombre del menú no lo coge»): el nombre se ve y se corrige en el propio diálogo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.restaurant = cls.env['res.partner'].create({'name': 'Casa Nombre', 'is_restaurant': True})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo nombre'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Ronda', 'min_capacity': 48})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú grupos', 'partner_id': cls.restaurant.id, 'cost_price': 20.0, 'ai_pending_review': True})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': 'Casa Nombre',
            'partner_id': cls.restaurant.id, 'menu_id': cls.menu.id})

    def _arch(self):
        view = self.env.ref('restagrup_restaurants.view_restaurant_search_line_quote_form')
        return etree.fromstring(self.env['restagrup.restaurant.search.line'].get_view(view.id)['arch'])

    def test_name_is_editable_in_the_dialog(self):
        fields_in_form = {node.get('name'): node for node in self._arch().iter('field')}
        self.assertIn('menu_name', fields_in_form)
        self.assertNotEqual(fields_in_form['menu_name'].get('readonly'), '1')

    def test_writing_the_name_renames_the_menu_and_keeps_the_year(self):
        self.line.menu_name = 'Menú peregrino'
        self.assertEqual(self.menu.name, 'Menú peregrino %s' % THIS_YEAR)

    def test_default_name_is_flagged_so_it_gets_a_real_one(self):
        self.assertTrue(self.line.menu_name_is_default)
        self.line.menu_name = 'Menú peregrino'
        self.assertFalse(self.line.menu_name_is_default)

    def test_menu_without_ai_review_is_not_flagged(self):
        self.menu.ai_pending_review = False
        self.assertFalse(self.line.menu_name_is_default)

    def test_dialog_shows_a_warning_for_default_names(self):
        alerts = [node for node in self._arch().iter('div')
                  if 'menu_name_is_default' in (node.get('invisible') or '')]
        self.assertTrue(alerts)
