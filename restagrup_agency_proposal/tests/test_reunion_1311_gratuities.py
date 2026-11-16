# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion1311Gratuities(TransactionCase):
    """Reunión 13/11 (P3): los comensales que pide la agencia YA incluyen las gratuidades. 55 con 2 gratuidades son
    53 que paga la agencia + 2 gratis; el restaurante cobra los 55."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        Partner = cls.env['res.partner']
        agency = Partner.create({'name': 'Viajes Gratis', 'is_company': True, 'email': 'grupos@gratis.example'})
        cls.restaurant = Partner.create({'name': 'Casa Gratuidad', 'is_restaurant': True, 'is_company': True,
                                         'email': 'casa@gratuidad.example', 'city': 'Barcelona'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Colegio Gratuidades', 'partner_id': agency.id})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Barcelona', 'pax': 55, 'gratuities': 2, 'event_date': '2026-12-14',
            'event_time': 13.5, 'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': cls.event.id, 'city': 'Barcelona', 'min_capacity': 55})
        cls.search_line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 10.0,
            'quote_received_date': '2026-11-13 10:00:00'})
        cls.search_line.action_toggle_chosen()
        cls.lead.action_pass_to_file()
        cls.order = cls.lead._restagrup_live_orders()
        cls.sale_line = cls.order.order_line.filtered(lambda l: not l.display_type)

    def _confirm(self):
        if self.order.state in ('draft', 'sent'):
            self.order.action_confirm()

    def _sheet_line(self):
        sheets = self.order.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')
        return sheets.order_line.filtered(lambda l: l.restagrup_sale_line_id == self.sale_line)

    # --- el servicio lleva las gratuidades y la venta sale ya con los que pagan ---

    def test_sale_line_from_service_pays_total_minus_gratuities(self):
        self.assertEqual((self.sale_line.product_uom_qty, self.sale_line.restagrup_gratuities), (53, 2))

    def test_service_info_shows_paying_plus_gratuities_equal_total(self):
        info = self.sale_line._restagrup_service_info()
        self.assertEqual((info['paying'], info['gratuities'], info['pax_total']), (53, 2, 55))

    # --- cambiar las gratuidades no suma comensales ---

    def test_setting_gratuities_on_sale_line_keeps_the_total(self):
        self.sale_line.restagrup_gratuities = 3
        self.assertEqual((self.sale_line.product_uom_qty, self.sale_line.restagrup_gratuities), (52, 3))

    def test_writing_quantity_and_gratuities_together_is_taken_as_is(self):
        self.sale_line.write({'product_uom_qty': 40, 'restagrup_gratuities': 1})
        self.assertEqual((self.sale_line.product_uom_qty, self.sale_line.restagrup_gratuities), (40, 1))

    def test_changing_gratuities_on_service_updates_the_sale_line(self):
        self.event.gratuities = 4
        self.assertEqual((self.sale_line.product_uom_qty, self.sale_line.restagrup_gratuities), (51, 4))

    def test_sale_line_without_gratuities_keeps_its_quantity(self):
        line = self.order.order_line.create({
            'order_id': self.order.id, 'product_id': self.sale_line.product_id.id, 'product_uom_qty': 30})
        self.assertEqual((line.product_uom_qty, line.restagrup_gratuities), (30, 0))

    # --- el restaurante cobra el total ---

    def test_restaurant_sheet_gets_total_diners(self):
        self._confirm()
        self.assertEqual(self._sheet_line().product_qty, 55)

    def test_restaurant_sheet_has_no_pending_pax_change(self):
        self._confirm()
        self.assertFalse([kind for kind, _text in self._sheet_line()._restagrup_changes() if kind == 'pax'])

    def test_more_gratuities_does_not_change_the_restaurant_sheet(self):
        self._confirm()
        self.sale_line.restagrup_gratuities = 3
        self.assertFalse([kind for kind, _text in self._sheet_line()._restagrup_changes() if kind == 'pax'])

    def test_more_diners_is_a_pax_change_for_the_restaurant(self):
        self._confirm()
        self.sale_line.product_uom_qty = 58
        changes = [text for kind, text in self._sheet_line()._restagrup_changes() if kind == 'pax']
        self.assertEqual(changes, ['Comensales 55 → 60'])
