# -*- coding: utf-8 -*-
"""Ronda de ajustes 11/11 (Conchita): fallos.

- El grupo de Rubén estaba en expediente con Mesón Los Arcos elegido pero sin pedido (pasó a expediente antes de que
  «Pasar a expediente» creara el pedido). «Enviar confirmación a la agencia» y las descargas daban «Este grupo aún
  no tiene pedido». Ahora, si hay restaurante elegido, el pedido se crea en ese momento.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


def _report(action):
    return action.get('context', {}).get('report_action', action)


def _send(env, action):
    """Reunión 12/11: el envío pasa por la ventana «Revisar y enviar»; se pulsa Enviar sin tocar nada."""
    while isinstance(action, dict) and action.get('res_model') == 'restagrup.send.wizard':
        action = env[action['res_model']].browse(action['res_id']).action_send()
    return action


@tagged('post_install', '-at_install')
class TestRonda1111FileWithoutOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.agency = cls.env['res.partner'].create({
            'name': 'Sol y Nubes Test', 'is_company': True, 'email': 'sol@nubes.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Test', 'is_restaurant': True, 'is_company': True,
            'email': 'meson@test.example', 'city': 'Sevilla'})

    def _old_file(self, choose=True):
        """Expediente «antiguo»: pasó de fase sin pedido."""
        lead = self.env['crm.lead'].create({'name': 'Grupo adulto', 'partner_id': self.agency.id})
        event = self.env['restagrup.lead.event'].create({
            'lead_id': lead.id, 'city': 'Sevilla', 'pax': 50, 'event_date': '2026-12-18', 'event_time': 14.0,
            'event_type_id': self.env.ref('restagrup_core.event_type_lunch').id})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 50})
        line = self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 16.0,
            'quote_received_date': '2026-11-09 10:00:00'})
        if choose:
            line.action_toggle_chosen()
        lead.with_context(restagrup_file_without_order=True).action_pass_to_file()
        self.assertEqual(lead.restagrup_stage_key, 'expediente')
        self.assertFalse(lead._restagrup_live_orders())
        return lead, search

    def test_download_agency_confirmation_creates_the_missing_order(self):
        lead, search = self._old_file()
        action = _report(lead.action_download_agency_confirmation())
        self.assertTrue(search.sale_order_id)
        self.assertEqual(search.sale_order_id.state, 'sale')
        self.assertEqual(action['context']['active_ids'], search.sale_order_id.ids)

    def test_send_agency_confirmation_creates_the_missing_order(self):
        lead, search = self._old_file()
        _send(self.env, lead.action_send_agency_confirmation())
        order = search.sale_order_id
        self.assertTrue(order)
        self.assertTrue(order.message_ids.filtered(lambda m: m.message_type == 'email'))

    def test_restaurant_confirmation_creates_the_missing_order(self):
        lead, search = self._old_file()
        _report(lead.action_download_restaurant_confirmation())
        self.assertTrue(search.sale_order_id.sudo().restaurant_po_ids)

    def test_without_chosen_restaurant_it_says_what_is_missing(self):
        lead, _search = self._old_file(choose=False)
        with self.assertRaises(UserError) as error:
            lead.action_download_agency_confirmation()
        self.assertIn('restaurante', str(error.exception))


@tagged('post_install', '-at_install')
class TestRonda1111BookingHeader(TransactionCase):
    """Cabecera de la confirmación: el teléfono de la agencia salía dos veces (TELÉFONO y CONTACTO). Orden pedido:
    agencia, contacto de la agencia con su teléfono y, al final, el agente de Restagrup con su contacto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Sol y Nubes Cabecera', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({
            'name': 'Conchita Cabecera', 'parent_id': cls.agency.id, 'phone': '+34 665 54 58 54',
            'email': 'conchita@cabecera.example'})
        cls.agent = cls.env['res.users'].create({
            'name': 'Rubén Agente', 'login': 'ruben.cabecera', 'phone': '+34 952 00 11 22',
            'email': 'ruben@restagrup.example'})
        product = cls.env['product.product'].create({'name': 'Menú cabecera', 'type': 'service'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.contact.id, 'user_id': cls.agent.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 42})]})

    def _header(self):
        html = self.env['ir.actions.report']._render_qweb_html(
            'restagrup_agency_proposal.report_booking_confirmation', self.order.ids)[0].decode()
        return html.split('DOCUMENTO', 1)[1].split('</table>', 1)[0]

    def test_agency_phone_is_not_repeated(self):
        self.assertEqual(self._header().count('+34 665 54 58 54'), 1)

    def test_order_agency_contact_then_restagrup_agent(self):
        header = self._header()
        positions = [header.index(text) for text in (
            'Sol y Nubes Cabecera', 'Conchita Cabecera', '+34 665 54 58 54', 'Rubén Agente', '+34 952 00 11 22')]
        self.assertEqual(positions, sorted(positions))

    def test_agency_own_phone_shows_when_it_has_one(self):
        self.agency.phone = '+34 952 99 88 77'
        header = self._header()
        self.assertIn('+34 952 99 88 77', header)
        self.assertEqual(header.count('+34 665 54 58 54'), 1)


@tagged('post_install', '-at_install')
class TestRonda1111PaidFromFile(TransactionCase):
    """Marcar el pago de la agencia desde el propio expediente (casilla «Pagado», como en su CRM): el justificante
    llega a veces por WhatsApp y no hace falta ir a «Pagos pendientes»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        agency = cls.env['res.partner'].create({'name': 'Agencia Pago', 'is_company': True, 'email': 'p@pago.example'})
        restaurant = cls.env['res.partner'].create({
            'name': 'Casa Pago', 'is_restaurant': True, 'is_company': True, 'email': 'c@pago.example',
            'city': 'Sevilla'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo pago', 'partner_id': agency.id})
        event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Sevilla', 'pax': 30, 'event_date': '2026-12-15', 'event_time': 13.5,
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'event_id': event.id, 'city': 'Sevilla', 'min_capacity': 30})
        line = cls.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
            'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 15.0, 'quote_received_date': '2026-11-09 10:00:00'})
        line.action_toggle_chosen()
        cls.lead.action_pass_to_file()
        cls.order = search.sale_order_id

    def test_ticking_paid_marks_the_order_paid(self):
        self.assertFalse(self.lead.restagrup_paid)
        self.lead.restagrup_paid = True
        self.assertTrue(self.order.restagrup_paid)
        self.assertTrue(self.order.restagrup_paid_date)

    def test_unticking_paid_unmarks_it(self):
        self.order.action_mark_paid()
        self.lead.invalidate_recordset(['restagrup_paid'])
        self.assertTrue(self.lead.restagrup_paid)
        self.lead.restagrup_paid = False
        self.assertFalse(self.order.restagrup_paid)

    def test_without_order_it_says_so(self):
        lead = self.env['crm.lead'].create({'name': 'Sin pedido pago'})
        with self.assertRaises(UserError):
            lead.restagrup_paid = True

    def test_paid_checkbox_is_on_the_file(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch']
        self.assertIn('name="restagrup_paid"', arch)


@tagged('post_install', '-at_install')
class TestRonda1111ChosenDishes(TransactionCase):
    """La proforma copiaba el menú entero (todas las opciones) y después lo elegido en «Observaciones». Con platos
    elegidos sale solo lo elegido, más lo que el menú incluye siempre (pan, bebidas, café)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        agency = cls.env['res.partner'].create({'name': 'Agencia Platos', 'is_company': True,
                                                'email': 'a@platos.example'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón Platos', 'is_restaurant': True, 'is_company': True, 'email': 'm@platos.example',
            'city': 'Sevilla'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú Mesón Platos', 'partner_id': cls.restaurant.id, 'cost_price': 14.0,
            'drinks_included': True, 'drinks_description': 'vino y agua',
            'line_ids': [(0, 0, {'course': course, 'name': name}) for course, name in (
                ('entrante', 'Espaguetis con Almejas'), ('entrante', 'Macarrones a la Napolitana'),
                ('principal', 'Bistec en salsa'), ('principal', 'Caldereta de Cordero'),
                ('postre', 'Postre'), ('bebida', 'Vino'), ('bebida', 'Agua'), ('otro', 'Pan'))]})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo platos', 'partner_id': agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Sevilla', 'min_capacity': 42})
        cls.line = cls.env[LINE].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_price_pp': 14.0,
            'menu_id': cls.menu.id, 'quote_received_date': '2026-11-09 10:00:00'})

    def _menu_text(self, notes):
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, notes)
        self.lead.action_create_joint_quote()
        order = self.search.sale_order_id
        return order.order_line[:1]._restagrup_service_info()['menu_text'], order

    def test_only_chosen_dishes_and_what_is_always_included(self):
        text, _order = self._menu_text('- Espaguetis con Almejas\n- Bistec en salsa')
        self.assertIn('Espaguetis con Almejas', text)
        self.assertIn('Bistec en salsa', text)
        self.assertNotIn('Macarrones', text)
        self.assertNotIn('Caldereta', text)
        for included in ('pan', 'vino', 'agua'):
            # Reunión 12/11 (7.2): cada bebida una sola vez (el vino y el agua van en «Bebidas: vino y agua»).
            self.assertEqual(text.lower().count(included), 1, text)

    def test_without_chosen_dishes_the_whole_menu_stays(self):
        text, _order = self._menu_text('')
        self.assertIn('Macarrones', text)
        self.assertIn('Caldereta', text)

    def test_chosen_dishes_are_not_repeated_in_observations(self):
        _text, order = self._menu_text('- Espaguetis con Almejas\n- Bistec en salsa')
        self.assertNotIn('Espaguetis', order.restagrup_observations or '')

    def test_free_text_menu_keeps_bread_drinks_and_coffee(self):
        self.menu.write({'line_ids': [(5, 0, 0)], 'drinks_description': False, 'description': (
            'ENTRANTES A ELEGIR:\nSALMOREJO\nENSALADILLA\nPRINCIPAL:\nPRESA IBÉRICA\nPan y bebidas incluidas\nCafé')})
        text, _order = self._menu_text('Salmorejo y presa')
        self.assertIn('Salmorejo y presa', text)
        self.assertNotIn('ENSALADILLA', text)
        self.assertIn('Pan y bebidas incluidas', text)
        self.assertIn('Café', text)
