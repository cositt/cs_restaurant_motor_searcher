# -*- coding: utf-8 -*-
import re

from lxml import etree

from odoo.tests.common import TransactionCase, tagged

KIND = 'lead_data_request'
TOP_MENUS = [
    'restagrup_service_orders.menu_peticiones',
    'restagrup_service_orders.menu_presupuestos',
    'restagrup_service_orders.menu_expedientes',
    'restagrup_service_orders.menu_restagrup_agencies',
    'restagrup_restaurants.menu_restaurant_list',
    'restagrup_agency_proposal.menu_pending_payments',
    'restagrup_agency_proposal.menu_restaurant_payments',
    'restagrup_service_orders.menu_terminados',
]


def _text(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.decode() if isinstance(html, bytes) else html))


@tagged('post_install', '-at_install')
class TestConchita1611(TransactionCase):
    """Correo de Conchita 16/11: gratuidades en los presupuestos, junto a los comensales (2.1, 2.2), y orden de la
    barra de menús (5)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '20')
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia gratuidades', 'is_company': True})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Gratuidades', 'is_restaurant': True, 'is_company': True, 'city': 'Madrid'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú grupos', 'partner_id': cls.restaurant.id, 'cost_price': 20})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo gratuidades', 'partner_id': cls.agency.id})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'pax': 55, 'gratuities': 2, 'event_date': '2026-12-14',
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Madrid', 'min_capacity': 55})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'interesado'})
        cls.line._apply_catalog_quote(cls.menu)

    # --- 2.1 gratuidades en los presupuestos ---

    def test_comparison_shows_paying_plus_gratuities(self):
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_agency_proposal.report_client_comparison', self.search.ids)
        self.assertIn('55 (53 + 2 gratuidades)', _text(html))

    def test_comparison_without_gratuities_keeps_the_plain_number(self):
        self.event.gratuities = 0
        self.assertEqual(self.search.restagrup_report_header()['pax_text'], '55')

    def _order(self):
        self.line.action_toggle_chosen()
        self.lead.action_pass_to_file()
        order = self.lead._restagrup_live_orders()
        self.assertTrue(order, 'el grupo debe tener pedido')
        return order

    def test_proposal_pdf_shows_gratuities_next_to_the_diners(self):
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_agency_proposal.action_report_restaurant_proposal', self._order().ids)
        self.assertIn('53 + 2 gratuidades', _text(html))

    def test_quote_pdf_title_shows_gratuities_next_to_pax(self):
        html, _kind = self.env['ir.actions.report']._render_qweb_html('sale.action_report_saleorder', self._order().ids)
        self.assertIn('PAX: 55 (53 + 2 gratuidades)', _text(html))

    def test_approx_options_pdf_shows_gratuities(self):
        pending = self.env['restagrup.pending.mail'].create({
            'kind': KIND, 'request_lead_id': self.lead.id, 'recipient_email': 'agencia@example.com',
            'subject': 'Opciones', 'body': 'Opciones orientativas'})
        html, _kind = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_restaurants.action_report_approx_options', pending.ids)
        self.assertIn('55 personas (53 + 2 gratuidades)', _text(html))

    # --- 2.2 junto al número de comensales ---

    def test_service_list_puts_gratuities_right_after_the_diners(self):
        arch = etree.fromstring(self.env['crm.lead'].get_view(view_type='form')['arch'])
        services = arch.xpath("//field[@name='restagrup_event_ids']/list")[0]
        names = [field.get('name') for field in services.iter('field')]
        self.assertEqual(names[names.index('pax') + 1], 'gratuities')

    # --- 5 orden de la barra ---

    def test_top_menu_order(self):
        menus = [self.env.ref(xmlid) for xmlid in TOP_MENUS]
        self.assertEqual([m.sequence for m in menus], sorted(m.sequence for m in menus))
        self.assertEqual(len({m.sequence for m in menus}), len(menus), 'sin empates de secuencia')
        others = self.env['ir.ui.menu'].search([
            ('parent_id', '=', menus[0].parent_id.id), ('id', 'not in', [m.id for m in menus])])
        self.assertTrue(all(m.sequence > menus[-1].sequence for m in others), others.mapped('name'))
