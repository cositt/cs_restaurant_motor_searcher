# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestApproxOptions(TransactionCase):
    """Cuando a la agencia le faltan datos, el correo que se los pide puede llevar ya opciones orientativas
    (restaurante + menú guardado + precio por persona), elegidas por una persona en «Pendientes de aprobar»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.Pending = cls.env['restagrup.pending.mail']
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.Wizard = cls.env['restagrup.approx.options.wizard']
        cls.owner = cls.env['res.users'].create({'name': 'Comercial Aprox', 'login': 'com_aprox'})
        cls.season = cls.Menu.default_get(['season'])['season']
        cls.taberna = cls._restaurant('Taberna Aprox', 'Sevilla', 90)
        cls.giralda = cls._restaurant('Giralda Aprox', 'Sevilla', 120)
        cls.small = cls._restaurant('Rincón Pequeño', 'Sevilla', 20)
        cls.malaga = cls._restaurant('Asador Málaga', 'Málaga', 80)
        cls.menu_taberna = cls._menu(cls.taberna, 'Menú grupos', 26.0)
        cls.menu_giralda = cls._menu(cls.giralda, 'Menú Giralda', 28.0)
        cls.menu_small = cls._menu(cls.small, 'Menú íntimo', 20.0)
        cls.menu_malaga = cls._menu(cls.malaga, 'Menú costa', 30.0)
        cls.menu_old = cls._menu(cls.taberna, 'Menú antiguo', 22.0, season=cls.season - 1)

    @classmethod
    def _restaurant(cls, name, city, capacity):
        return cls.env['res.partner'].create({
            'name': name, 'is_restaurant': True, 'city': city, 'restaurant_capacity': capacity})

    @classmethod
    def _menu(cls, partner, name, cost, **extra):
        vals = {'name': name, 'partner_id': partner.id, 'cost_price': cost, 'menu_type': 'almuerzo',
                'description': 'Entrantes para compartir\nPrincipal a elegir\nPostre casero'}
        vals.update(extra)
        return cls.Menu.create(vals)

    def setUp(self):
        super().setUp()
        self.lead = self.env['crm.lead'].create({
            'name': 'Grupo senior Sevilla', 'email_from': 'lucia@agencia.example.com', 'user_id': self.owner.id})
        self.env['restagrup.lead.event'].create({'lead_id': self.lead.id, 'city': 'Sevilla', 'pax': 45})
        self.lead._restagrup_ask_for_missing_data()
        self.pending = self.Pending.search([('request_lead_id', '=', self.lead.id)])
        self.assertEqual(len(self.pending), 1)

    def _open_wizard(self, pending=None):
        action = (pending or self.pending).action_open_approx_options()
        return self.Wizard.browse(action['res_id'])

    def _select(self, wizard, *menus):
        wizard.line_ids.filtered(lambda line: line.menu_id in menus).write({'selected': True})

    # --- el asistente ---

    def test_wizard_starts_filtered_by_city_and_pax_of_the_request(self):
        wizard = self._open_wizard()
        self.assertEqual(wizard.city, 'Sevilla')
        self.assertEqual(wizard.pax, 45)
        self.assertEqual(wizard.line_ids.menu_id, self.menu_taberna | self.menu_giralda,
                         'fuera: otra ciudad, aforo insuficiente y temporadas pasadas')
        self.assertFalse(any(wizard.line_ids.mapped('selected')))

    def test_menu_capacity_also_limits_the_candidates(self):
        self.menu_giralda.max_pax = 40
        wizard = self._open_wizard()
        self.assertEqual(wizard.line_ids.menu_id, self.menu_taberna)

    def test_refresh_rebuilds_the_list_with_new_filters(self):
        wizard = self._open_wizard()
        wizard.write({'city': '', 'pax': 0})
        wizard.action_refresh()
        mine = self.menu_taberna | self.menu_giralda | self.menu_small | self.menu_malaga
        self.assertEqual(wizard.line_ids.menu_id & (mine | self.menu_old), mine,
                         'sin ciudad ni comensales: todos los de la temporada')

    def test_lines_show_the_client_price_never_the_cost(self):
        wizard = self._open_wizard()
        line = wizard.line_ids.filtered(lambda l: l.menu_id == self.menu_taberna)
        self.assertAlmostEqual(line.price_per_person, 31.20)

    def test_only_pending_data_requests_to_the_agency_accept_options(self):
        self.pending.action_discard()
        with self.assertRaises(UserError):
            self.pending.action_open_approx_options()

    def test_applying_without_selection_is_refused(self):
        wizard = self._open_wizard()
        with self.assertRaises(UserError):
            wizard.action_apply()

    # --- el correo ---

    def test_applying_adds_the_options_to_the_same_email_that_asks_for_the_missing_data(self):
        wizard = self._open_wizard()
        self._select(wizard, self.menu_taberna, self.menu_giralda)
        wizard.action_apply()
        options = self.pending.option_ids
        self.assertEqual(options.partner_id, self.taberna | self.giralda)
        self.assertEqual(options.sorted('price_per_person').mapped('price_per_person'), [31.20, 33.60])
        body = self.pending.body
        self.assertIn('Fecha', body, 'sigue pidiendo lo que falta')
        self.assertIn('orientativ', body.lower())
        self.assertIn('Taberna Aprox', body)
        self.assertIn('31,20 €', body)
        self.assertIn('IVA incluido', body)
        self.assertIn('Principal a elegir', body, 'lleva el menú de cada opción')
        self.assertNotIn('26,00', body, 'nunca el coste del restaurante')
        self.assertLess(body.index('Fecha'), body.index('Taberna Aprox'))
        self.assertTrue(body.rstrip().endswith(self.owner.name), 'la firma sigue al final')

    def test_restaurant_names_can_be_hidden(self):
        wizard = self._open_wizard()
        wizard.show_restaurants = False
        self._select(wizard, self.menu_taberna)
        wizard.action_apply()
        self.assertNotIn('Taberna Aprox', self.pending.body)
        self.assertIn('Opción 1', self.pending.body)
        self.assertFalse(self.pending.option_show_restaurants)

    def test_applying_again_replaces_the_options(self):
        wizard = self._open_wizard()
        self._select(wizard, self.menu_taberna, self.menu_giralda)
        wizard.action_apply()
        wizard = self._open_wizard()
        self.assertEqual(wizard.line_ids.filtered('selected').menu_id, self.menu_taberna | self.menu_giralda,
                         'al volver a abrir salen marcadas las que ya están')
        wizard.line_ids.filtered(lambda l: l.menu_id == self.menu_giralda).selected = False
        wizard.action_apply()
        self.assertEqual(self.pending.option_ids.menu_id, self.menu_taberna)
        self.assertEqual(self.pending.body.count('Taberna Aprox'), 1)
        self.assertNotIn('Giralda Aprox', self.pending.body)

    def test_removing_the_options_leaves_the_plain_data_request(self):
        plain = self.pending.body
        wizard = self._open_wizard()
        self._select(wizard, self.menu_taberna)
        wizard.action_apply()
        self.pending.action_clear_approx_options()
        self.assertFalse(self.pending.option_ids)
        self.assertEqual(self.pending.body, plain)

    def test_option_keeps_what_was_offered_even_if_the_menu_changes_later(self):
        wizard = self._open_wizard()
        self._select(wizard, self.menu_taberna)
        wizard.action_apply()
        self.menu_taberna.write({'cost_price': 40.0, 'name': 'Menú nuevo'})
        option = self.pending.option_ids
        self.assertAlmostEqual(option.price_per_person, 31.20)
        self.assertEqual(option.menu_name, 'Menú grupos')

    # --- al aprobar ---

    def test_approving_sends_the_email_with_the_orientative_pdf(self):
        wizard = self._open_wizard()
        self._select(wizard, self.menu_taberna)
        wizard.action_apply()
        self.pending.action_approve()
        self.assertEqual(self.pending.state, 'sent')
        sent = self.lead.message_ids.filtered(lambda m: m.message_type == 'email' and m.subject == self.pending.subject)
        self.assertEqual(len(sent), 1)
        self.assertIn('Taberna Aprox', sent.body)
        self.assertEqual(len(sent.attachment_ids), 1)
        self.assertIn('Opciones orientativas', sent.attachment_ids.name)

    def test_approving_without_options_sends_no_attachment(self):
        self.pending.action_approve()
        sent = self.lead.message_ids.filtered(lambda m: m.message_type == 'email' and m.subject == self.pending.subject)
        self.assertEqual(len(sent), 1)
        self.assertFalse(sent.attachment_ids)

    def test_report_marks_the_options_as_orientative(self):
        wizard = self._open_wizard()
        self._select(wizard, self.menu_taberna)
        wizard.action_apply()
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_restaurants.action_report_approx_options', self.pending.ids)
        html = html.decode()
        self.assertIn('Orientativo', html)
        self.assertIn('Taberna Aprox', html)
        self.assertNotIn('26,00', html)
