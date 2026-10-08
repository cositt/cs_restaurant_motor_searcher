# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRestaurantMenus(TransactionCase):
    """C: menús como productos con precio, ligados a un restaurante."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client_partner = cls.env['res.partner'].create({
            'name': 'Cliente Menús', 'email': 'cliente@example.com',
        })
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Grupo menús', 'partner_id': cls.client_partner.id,
        })
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Toledo', 'min_capacity': 47,
        })
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Asador con menús', 'is_restaurant': True, 'email': 'asador@example.com',
        })
        cls.other_restaurant = cls.env['res.partner'].create({
            'name': 'Otro restaurante', 'is_restaurant': True,
        })
        cls.menu_lunch = cls._create_menu('Menú grupo — comida', cls.restaurant, 32.0)
        cls.menu_dinner = cls._create_menu('Menú grupo — cena', cls.restaurant, 41.5)
        cls.foreign_menu = cls._create_menu('Menú de otro', cls.other_restaurant, 20.0)

    @classmethod
    def _create_menu(cls, name, restaurant, price):
        # 'price' es lo que cobra el restaurante (standard_price); el del cliente sale con el margen
        return cls.env['product.template'].create({
            'name': name, 'type': 'service', 'standard_price': price,
            'sale_ok': True, 'restaurant_id': restaurant.id,
        })

    def _chosen_line(self, restaurant=None, quote_amount=0):
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'partner', 'name': 'Elegido',
            'partner_id': (restaurant or self.restaurant).id,
            'etiqueta': 'presupuesto_recibido', 'quote_amount': quote_amount,
        })
        line.action_toggle_chosen()
        return line

    def _open_wizard(self):
        action = self.search.action_create_sale_order()
        return self.env[action['res_model']].browse(action['res_id'])

    # --- modelo: producto ligado a restaurante ---

    def test_partner_lists_its_menus(self):
        self.assertEqual(self.restaurant.menu_ids, self.menu_lunch | self.menu_dinner)
        self.assertNotIn(self.foreign_menu, self.restaurant.menu_ids)

    def test_product_restaurant_must_be_a_restaurant(self):
        not_restaurant = self.env['res.partner'].create({'name': 'Particular'})
        with self.assertRaises(ValidationError):
            self.env['product.template'].create({
                'name': 'Menú inválido', 'type': 'service', 'restaurant_id': not_restaurant.id,
            })

    # --- línea de venta: restaurante se rellena solo desde el menú ---

    def _order_with_line(self, product, **line_vals):
        return self.env['sale.order'].create({
            'partner_id': self.client_partner.id,
            'order_line': [(0, 0, dict({
                'product_id': product.product_variant_id.id, 'product_uom_qty': 10,
            }, **line_vals))],
        })

    def test_line_takes_restaurant_from_menu_product(self):
        order = self._order_with_line(self.menu_lunch)
        self.assertEqual(order.order_line.restaurant_id, self.restaurant)

    def test_line_keeps_explicit_restaurant(self):
        order = self._order_with_line(self.menu_lunch, restaurant_id=self.other_restaurant.id)
        self.assertEqual(order.order_line.restaurant_id, self.other_restaurant)

    def test_line_without_menu_product_has_no_restaurant(self):
        plain = self.env['product.template'].create({'name': 'Producto normal', 'type': 'service'})
        order = self._order_with_line(plain)
        self.assertFalse(order.order_line.restaurant_id)

    # --- crear presupuesto: con importe cotizado, línea directa; sin él, asistente si hay menús ---

    def test_create_sale_order_opens_wizard_when_restaurant_has_menus_and_no_quote(self):
        self._chosen_line()
        action = self.search.action_create_sale_order()
        self.assertEqual(action['res_model'], 'restagrup.menu.selection.wizard')
        self.assertFalse(self.search.sale_order_id)

    def test_quote_amount_skips_the_menu_wizard_even_if_the_restaurant_has_menus(self):
        self._chosen_line(quote_amount=1024)
        action = self.search.action_create_sale_order()
        self.assertEqual(action['res_model'], 'sale.order')
        order = self.search.sale_order_id
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_uom_qty, 47)  # comensales de la búsqueda
        self.assertAlmostEqual(order.order_line.restagrup_unit_cost, 1024 / 47, places=2)

    def test_create_sale_order_keeps_legacy_path_without_menus(self):
        self._chosen_line(restaurant=self.other_restaurant)
        self.env['product.template'].search([('restaurant_id', '=', self.other_restaurant.id)]).unlink()
        self.search.action_create_sale_order()
        self.assertTrue(self.search.sale_order_id)
        self.assertEqual(len(self.search.sale_order_id.order_line), 1)

    def test_wizard_prefills_menus_of_chosen_restaurant_only(self):
        self._chosen_line()
        wizard = self._open_wizard()
        self.assertEqual(
            wizard.line_ids.mapped('product_tmpl_id'), self.menu_lunch | self.menu_dinner,
        )
        self.assertTrue(all(l.quantity == 47 for l in wizard.line_ids))
        self.assertFalse(any(l.selected for l in wizard.line_ids))

    def test_wizard_creates_one_sale_line_per_selected_menu(self):
        chosen = self._chosen_line(quote_amount=0)
        wizard = self._open_wizard()
        lunch = wizard.line_ids.filtered(lambda l: l.product_tmpl_id == self.menu_lunch)
        dinner = wizard.line_ids.filtered(lambda l: l.product_tmpl_id == self.menu_dinner)
        lunch.write({'selected': True, 'quantity': 47})
        dinner.write({'selected': True, 'quantity': 30})
        wizard.action_confirm()
        order = self.search.sale_order_id
        self.assertEqual(len(order.order_line), 2)
        by_tmpl = {l.product_template_id: l for l in order.order_line}
        self.assertEqual(by_tmpl[self.menu_lunch].product_uom_qty, 47)
        self.assertAlmostEqual(by_tmpl[self.menu_lunch].price_unit, 38.4)  # 32 + 20 %
        self.assertEqual(by_tmpl[self.menu_dinner].product_uom_qty, 30)
        self.assertAlmostEqual(by_tmpl[self.menu_dinner].price_unit, 49.8)  # 41,5 + 20 %
        for line in order.order_line:
            self.assertEqual(line.restaurant_id, self.restaurant)
            self.assertEqual(line.restagrup_search_line_id, chosen)
        self.assertEqual(order.partner_id, self.client_partner)

    def test_wizard_price_is_restaurant_price_plus_configured_margin(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.default_margin_percent', '25')
        self._chosen_line(quote_amount=0)
        wizard = self._open_wizard()
        wizard.line_ids.filtered(lambda l: l.product_tmpl_id == self.menu_lunch).selected = True
        wizard.action_confirm()
        self.assertAlmostEqual(self.search.sale_order_id.order_line.price_unit, 40.0)  # 32 + 25 %

    def test_wizard_price_defaults_to_restaurant_price_plus_20_percent(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.default_margin_percent')]).unlink()
        self._chosen_line(quote_amount=0)
        wizard = self._open_wizard()
        wizard.line_ids.filtered(lambda l: l.product_tmpl_id == self.menu_lunch).selected = True
        wizard.action_confirm()
        self.assertAlmostEqual(self.search.sale_order_id.order_line.price_unit, 38.4)

    def test_manual_line_with_menu_gets_restaurant_price_plus_margin(self):
        order = self._order_with_line(self.menu_lunch)
        self.assertAlmostEqual(order.order_line.price_unit, 38.4)

    def test_menu_without_restaurant_price_falls_back_to_list_price(self):
        menu = self.env['product.template'].create({
            'name': 'Menú sin coste', 'type': 'service', 'list_price': 50.0,
            'sale_ok': True, 'restaurant_id': self.restaurant.id,
        })
        order = self._order_with_line(menu)
        self.assertAlmostEqual(order.order_line.price_unit, 50.0)

    def test_client_price_field_shows_restaurant_price_plus_margin(self):
        self.assertAlmostEqual(self.menu_lunch.restagrup_client_price, 38.4)

    def test_client_price_is_zero_for_products_that_are_not_menus(self):
        plain = self.env['product.template'].create({'name': 'Otro', 'type': 'service', 'standard_price': 10})
        self.assertEqual(plain.restagrup_client_price, 0.0)

    def test_service_sheet_carries_the_restaurant_price_not_the_client_price(self):
        self._chosen_line(quote_amount=0)
        wizard = self._open_wizard()
        wizard.line_ids.write({'selected': True})
        wizard.action_confirm()
        order = self.search.sale_order_id
        order.action_confirm()
        self.assertEqual(
            sorted(order.restaurant_po_ids.order_line.mapped('price_unit')), [32.0, 41.5],
        )

    def test_wizard_requires_at_least_one_selected_menu(self):
        self._chosen_line()
        wizard = self._open_wizard()
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(self.search.sale_order_id)

    def test_wizard_rejects_non_positive_quantity(self):
        self._chosen_line()
        wizard = self._open_wizard()
        line = wizard.line_ids[0]
        line.write({'selected': True, 'quantity': 0})
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_confirming_menu_order_creates_service_sheet_with_menu_lines(self):
        self._chosen_line()
        wizard = self._open_wizard()
        wizard.line_ids.write({'selected': True})
        wizard.action_confirm()
        order = self.search.sale_order_id
        order.action_confirm()
        self.assertEqual(len(order.restaurant_po_ids), 1)
        self.assertEqual(len(order.restaurant_po_ids.order_line), 2)

    def test_create_sale_order_is_idempotent_with_menus(self):
        self._chosen_line()
        wizard = self._open_wizard()
        wizard.line_ids[0].selected = True
        wizard.action_confirm()
        order = self.search.sale_order_id
        action = self.search.action_create_sale_order()
        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(self.search.sale_order_id, order)

    # --- permisos: los tests corren como superusuario, un comercial real no ---

    def test_salesman_can_use_menu_wizard(self):
        """Regresión: el asistente sin ir.model.access.csv fallaba en el navegador
        con 'Ningún grupo permite esta operación' aunque los tests pasaran."""
        salesman = self.env['res.users'].create({
            'name': 'Comercial Test', 'login': 'comercial_menus_test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        for model in ('restagrup.menu.selection.wizard', 'restagrup.menu.selection.wizard.line'):
            for operation in ('read', 'create', 'write', 'unlink'):
                self.assertTrue(
                    self.env[model].with_user(salesman).has_access(operation),
                    '%s: falta acceso de %s para un comercial' % (model, operation),
                )


@tagged('post_install', '-at_install')
class TestPartnerMenuTabs(TransactionCase):
    """En la ficha del restaurante hay una sola pestaña «Menús» para el personal: la del catálogo de menús."""

    def _form_arch(self, user):
        return self.env['res.partner'].with_user(user).get_view(view_type='form')['arch']

    def test_regular_user_sees_a_single_menus_tab_with_the_catalog(self):
        user = self.env['res.users'].create({
            'name': 'Comercial pestañas', 'login': 'tabs_user',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        arch = self._form_arch(user)
        self.assertEqual(arch.count('string="Menús"'), 1)
        self.assertIn('restaurant_menu_ids', arch)
        self.assertNotIn('menu_ids"', arch.replace('restaurant_menu_ids', ''))

    def test_admin_still_reaches_the_product_menus_under_another_name(self):
        arch = self._form_arch(self.env.ref('base.user_admin'))
        self.assertIn('Menús de producto', arch)
        self.assertEqual(arch.count('string="Menús"'), 1)
