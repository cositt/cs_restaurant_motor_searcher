# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMultiEventOrder(TransactionCase):
    """Un grupo con varios eventos acumula sus restaurantes elegidos en un único presupuesto
    mientras no esté firmado; si ya está firmado, el evento nuevo va a un presupuesto adicional."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env['res.partner'].create({'name': 'Agencia multi', 'email': 'ag@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo multi', 'partner_id': cls.client.id})
        cls.lunch = cls.env.ref('restagrup_core.event_type_lunch')
        cls.dinner = cls.env.ref('restagrup_core.event_type_dinner')
        cls.rest_a = cls.env['res.partner'].create({'name': 'Casa Málaga', 'is_restaurant': True})
        cls.rest_b = cls.env['res.partner'].create({'name': 'Casa Sevilla', 'is_restaurant': True})

    def _event_search(self, city='Málaga', event_type=None, date='2026-11-15', pax=42):
        event = self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': city, 'pax': pax, 'event_date': date,
            'event_type_id': (event_type or self.dinner).id,
        })
        return self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'event_id': event.id, 'city': city, 'min_capacity': pax,
        })

    def _choose(self, search, restaurant, amount=1000):
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name,
            'partner_id': restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': amount,
        })
        line.action_toggle_chosen()
        return line

    def _create_order(self, search, restaurant, amount=1000):
        self._choose(search, restaurant, amount)
        search.action_create_sale_order()
        return search.sale_order_id

    # --- primer evento: crea el presupuesto del grupo ---

    def test_first_event_creates_the_group_order_linked_to_the_lead(self):
        search = self._event_search(city='Málaga', event_type=self.dinner, date='2026-11-15')
        order = self._create_order(search, self.rest_a)
        self.assertEqual(order.opportunity_id, self.lead)
        line = order.order_line
        self.assertEqual(str(line.service_date), '2026-11-15')
        self.assertEqual(line.service_event_type_id, self.dinner)

    def test_event_info_is_in_the_line_description(self):
        search = self._event_search(city='Sevilla', event_type=self.dinner, date='2026-11-16', pax=40)
        line = self._create_order(search, self.rest_b).order_line
        self.assertIn('Cena', line.name)
        self.assertIn('16/11', line.name)
        self.assertIn('Casa Sevilla', line.name)

    # --- más eventos: se acumulan en el mismo presupuesto mientras no esté firmado ---

    def test_second_event_adds_a_line_to_the_same_open_order(self):
        first = self._event_search(city='Málaga', event_type=self.lunch, date='2026-11-15')
        order = self._create_order(first, self.rest_a, amount=1000)
        second = self._event_search(city='Sevilla', event_type=self.dinner, date='2026-11-16', pax=40)
        self._choose(second, self.rest_b, 800)
        second.action_create_sale_order()
        self.assertEqual(second.sale_order_id, order)
        self.assertEqual(len(order.order_line), 2)
        self.assertEqual(order.order_line.mapped('restaurant_id'), self.rest_a | self.rest_b)

    def test_totals_accumulate_across_events(self):
        first = self._event_search(event_type=self.lunch)
        order = self._create_order(first, self.rest_a, amount=1000)
        second = self._event_search(city='Sevilla', event_type=self.dinner, date='2026-11-16')
        self._create_order(second, self.rest_b, amount=800)
        self.assertAlmostEqual(sum(l.price_unit * l.product_uom_qty for l in order.order_line), 1200.0 + 960.0, places=2)  # cada importe + 20 % de margen

    def test_every_search_of_the_group_reaches_the_sale_created_stage(self):
        first = self._event_search(event_type=self.lunch)
        order = self._create_order(first, self.rest_a)
        second = self._event_search(city='Sevilla')
        self._create_order(second, self.rest_b)
        self.assertEqual(first.sale_order_id, order)
        self.assertEqual(set((first | second).mapped('pipeline_stage')), {'sale_created'})

    def test_sent_but_unsigned_order_still_accepts_events_and_leaves_a_note(self):
        first = self._event_search(event_type=self.lunch)
        order = self._create_order(first, self.rest_a)
        order.write({'state': 'sent'})
        second = self._event_search(city='Sevilla')
        self._create_order(second, self.rest_b)
        self.assertEqual(second.sale_order_id, order)
        self.assertIn('reenv', ' '.join(order.message_ids.mapped('body')).lower())

    def test_menus_path_adds_to_the_open_order(self):
        menu_restaurant = self.env['res.partner'].create({'name': 'Con menús', 'is_restaurant': True})
        menu = self.env['product.template'].create({
            'name': 'Menú evento', 'type': 'service', 'standard_price': 25.0,
            'sale_ok': True, 'restaurant_id': menu_restaurant.id,
        })
        first = self._event_search(event_type=self.lunch)
        order = self._create_order(first, self.rest_a)
        second = self._event_search(city='Toledo', event_type=self.dinner, date='2026-11-17', pax=30)
        self._choose(second, menu_restaurant)
        second._create_sale_order_from_menus([(menu.product_variant_id, 30)])
        self.assertEqual(second.sale_order_id, order)
        menu_line = order.order_line.filtered(lambda l: l.restaurant_id == menu_restaurant)
        self.assertEqual(menu_line.service_event_type_id, self.dinner)
        self.assertEqual(menu_line.product_uom_qty, 30)

    # --- presupuesto firmado: el evento nuevo va a un presupuesto adicional ---

    def test_confirmed_order_is_untouched_and_an_additional_one_is_created(self):
        first = self._event_search(event_type=self.lunch)
        original = self._create_order(first, self.rest_a)
        original.action_confirm()
        second = self._event_search(city='Sevilla', event_type=self.dinner, date='2026-11-16')
        additional = self._create_order(second, self.rest_b)
        self.assertNotEqual(additional, original)
        self.assertEqual(len(original.order_line), 1)
        self.assertEqual(original.state, 'sale')
        self.assertEqual(additional.opportunity_id, self.lead)
        self.assertEqual(additional.state, 'draft')

    def test_additional_order_knows_it_is_additional_and_points_to_the_first(self):
        first = self._event_search(event_type=self.lunch)
        original = self._create_order(first, self.rest_a)
        original.action_confirm()
        second = self._event_search(city='Sevilla')
        additional = self._create_order(second, self.rest_b)
        self.assertTrue(additional.restagrup_is_additional)
        self.assertEqual(additional.restagrup_first_order_id, original)
        self.assertFalse(original.restagrup_is_additional)

    def test_a_cancelled_order_does_not_make_the_next_one_additional(self):
        first = self._event_search(event_type=self.lunch)
        original = self._create_order(first, self.rest_a)
        original._action_cancel()
        second = self._event_search(city='Sevilla')
        new_order = self._create_order(second, self.rest_b)
        self.assertNotEqual(new_order, original)
        self.assertFalse(new_order.restagrup_is_additional)

    def test_each_order_generates_its_own_service_sheet_for_the_same_restaurant(self):
        first = self._event_search(event_type=self.lunch, date='2026-11-15')
        original = self._create_order(first, self.rest_a)
        original.action_confirm()
        second = self._event_search(event_type=self.dinner, date='2026-11-16')
        additional = self._create_order(second, self.rest_a)
        additional.action_confirm()
        sheets = self.env['purchase.order'].search([('partner_id', '=', self.rest_a.id)])
        self.assertEqual(len(sheets), 2)
        self.assertEqual(set(sheets.mapped('restagrup_sale_order_id')), {original, additional})

    # --- un grupo de un solo evento (o sin evento) va exactamente como antes ---

    def test_search_without_event_behaves_as_before(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid', 'min_capacity': 20,
        })
        line = self._create_order(search, self.rest_a, amount=500).order_line
        self.assertFalse(line.service_date)
        self.assertFalse(line.service_event_type_id)
        self.assertIn('Servicio en Casa Málaga', line.name)
        self.assertNotIn('·', line.name.split('—')[0])

    # --- migración: comida/cena antiguos pasan al tipo de evento nuevo ---

    def test_old_meal_values_are_copied_to_the_event_type(self):
        order = self.env['sale.order'].create({'partner_id': self.client.id, 'order_line': [
            (0, 0, {'name': 'Antigua comida', 'display_type': 'line_note'}),
        ]})
        service = self.env.ref('restagrup_service_orders.product_restaurant_service')
        lunch_line, dinner_line, typed_line = self.env['sale.order.line'].create([
            {'order_id': order.id, 'product_id': service.id, 'service_meal': 'lunch'},
            {'order_id': order.id, 'product_id': service.id, 'service_meal': 'dinner'},
            {'order_id': order.id, 'product_id': service.id, 'service_meal': 'lunch',
             'service_event_type_id': self.env.ref('restagrup_core.event_type_aperitif').id},
        ])
        self.env['sale.order.line']._restagrup_fill_event_type_from_meal()
        self.assertEqual(lunch_line.service_event_type_id, self.lunch)
        self.assertEqual(dinner_line.service_event_type_id, self.dinner)
        self.assertEqual(typed_line.service_event_type_id.name, 'Aperitivo', 'No se pisa un tipo ya elegido.')
