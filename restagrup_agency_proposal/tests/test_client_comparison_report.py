# -*- coding: utf-8 -*-
import re

from odoo.tests.common import TransactionCase, tagged

REPORT = 'restagrup_agency_proposal.report_client_comparison'


@tagged('post_install', '-at_install')
class TestClientComparisonReport(TransactionCase):
    """PDF comparativo para el cliente: menú y precio por persona de cada restaurante con presupuesto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        lead = cls.env['crm.lead'].create({'name': 'Grupo Whitfield'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Málaga', 'min_capacity': 40,
        })
        cls.cheap = cls._quote('Asador Sierra Blanca', 1000.0, 'Gazpachuelo malagueño')
        cls._quote('Casa Cara', 2000.0, 'Cordero lechal')
        cls._quote('Mesón Sin Confirmar', 500.0, 'Plato secreto', etiqueta='solicitado')

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

    def _html(self):
        html, _kind = self.env['ir.actions.report']._render_qweb_html(REPORT, self.search.ids)
        return html.decode()

    def test_report_lists_each_confirmed_restaurant_with_its_menu(self):
        html = self._html()
        for text in ('Asador Sierra Blanca', 'Gazpachuelo malagueño', 'Casa Cara', 'Cordero lechal'):
            self.assertIn(text, html)

    def test_report_leaves_out_unconfirmed_quotes(self):
        html = self._html()
        self.assertNotIn('Mesón Sin Confirmar', html)
        self.assertNotIn('Plato secreto', html)

    def test_report_shows_client_price_per_person_and_never_the_restaurant_cost(self):
        html = self._html()
        text = re.sub(r'<[^>]+>', ' ', html)
        self.assertRegex(text, r'30[.,]00')  # (1000 + 20 %) / 40 personas
        self.assertNotRegex(text, r'1[.,\s\xa0]?200[.,]00')  # el total no sale en el presupuesto
        self.assertNotRegex(text, r'(?<!\d)1[.,\s\xa0]?000[.,]00')  # coste del restaurante
        self.assertNotRegex(text, r'31[.,]77')  # ni el precio del menú del restaurante
        self.assertNotRegex(text, r'(?<!\d)40[.,]00')  # ni el margen por persona

    def test_report_is_registered_on_the_search_model(self):
        report = self.env.ref(REPORT.replace('report_client_comparison', 'action_report_client_comparison'))
        self.assertEqual(report.model, 'restagrup.restaurant.search')
        self.assertEqual(report.report_type, 'qweb-pdf')

    def test_hidden_restaurant_leaves_out_name_and_address(self):
        self.cheap.partner_id.write({'city': 'Zahara-Test', 'street': 'Calle Secreta 1'})
        visible = self._html()
        self.assertIn('Asador Sierra Blanca', visible)
        self.assertIn('Zahara-Test', visible)
        self.search.restaurant_visible = False
        hidden = self._html()
        for text in ('Asador Sierra Blanca', 'Casa Cara', 'Zahara-Test', 'Calle Secreta'):
            self.assertNotIn(text, hidden)
        self.assertIn('Opción 1', hidden)
        self.assertIn('Gazpachuelo malagueño', hidden)  # el menú sí
