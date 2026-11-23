# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestRonda2011(TransactionCase):
    """Ronda de ajustes de Conchita (correo del 20/11): rótulos, columna del grupo, accesos directos a la ficha del
    restaurante y aviso de respuesta que lleva a la petición."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.owner = cls.env['res.users'].create({'name': 'Comercial 2011', 'login': 'com_2011', 'email': 'c2011@example.test'})
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia 2011', 'email': 'a2011@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa 2011', 'is_restaurant': True, 'email': 'casa-2011@example.com'})

    def _arch(self, model, view_type):
        arch = self.env[model].get_view(view_type=view_type)['arch']
        return etree.fromstring(arch)

    def _sheet(self):
        product = self.env['product.template'].create({
            'name': 'Menú 2011', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0,
            'sale_ok': True, 'restaurant_id': self.restaurant.id}).product_variant_id
        lead = self.env['crm.lead'].create({'name': 'Grupo escolar 2011', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 30, 'service_hour': 20.5,
                                   'service_date': fields.Date.context_today(lead) + timedelta(days=5)})]})
        order.action_confirm()
        return order, order.restaurant_po_ids

    # --- 3.1 pestaña «Pendiente para cerrar» ---

    def test_close_tab_is_called_pendiente_para_cerrar(self):
        tree = self._arch('crm.lead', 'form')
        pages = tree.xpath('//page[@name="restagrup_close"]')
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].get('string'), 'Pendiente para cerrar')

    # --- 5.2 nombre del grupo en las listas de pagos ---

    def test_pending_payments_list_shows_the_group_name(self):
        action = self.env.ref('restagrup_agency_proposal.action_pending_payments')
        view = self.env[action.res_model].get_view(view_id=action.view_ids[:1].view_id.id, view_type='list')
        self.assertTrue(etree.fromstring(view['arch']).xpath('//field[@name="opportunity_id"]'))

    def test_restaurant_payments_list_shows_the_group_name(self):
        order, sheet = self._sheet()
        self.assertEqual(sheet.restagrup_group_name, 'Grupo escolar 2011')
        action = self.env.ref('restagrup_agency_proposal.action_restaurant_payments')
        view = self.env[action.res_model].get_view(view_id=action.view_ids[:1].view_id.id, view_type='list')
        self.assertTrue(etree.fromstring(view['arch']).xpath('//field[@name="restagrup_group_name"]'))

    # --- 5.4 ficha del restaurante desde la hoja de servicio ---

    def test_sheet_opens_the_restaurant_record(self):
        order, sheet = self._sheet()
        action = sheet.action_open_restaurant()
        self.assertEqual((action['res_model'], action['res_id']), ('res.partner', self.restaurant.id))
        tree = self._arch('purchase.order', 'form')
        self.assertTrue(tree.xpath('//button[@name="action_open_restaurant"]'))

    # --- 1.3 ficha del restaurante desde la pestaña Propuesta ---

    def test_proposal_row_opens_the_restaurant_record(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo propuesta 2011', 'partner_id': self.agency.id})
        search = self.env['restagrup.restaurant.search'].create({'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 20})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'email': self.restaurant.email, 'etiqueta': 'solicitado'})
        action = line.action_open_restaurant()
        self.assertEqual((action['res_model'], action['res_id']), ('res.partner', self.restaurant.id))
        tree = self._arch('crm.lead', 'form')
        self.assertTrue(tree.xpath('//button[@name="action_open_restaurant"]'))

    # --- 1.4 el aviso de respuesta del restaurante lleva a la petición ---

    def test_restaurant_reply_activity_hangs_from_the_request_and_clears_when_reviewed(self):
        lead = self.env['crm.lead'].create({'name': 'Grupo aviso 2011', 'partner_id': self.agency.id, 'user_id': self.owner.id})
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': lead.id, 'city': 'Madrid', 'min_capacity': 20, 'user_id': self.owner.id})
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'email': self.restaurant.email, 'etiqueta': 'solicitado'})
        with patch(LLM_PATH, return_value=({'importe': None, 'notas': None}, 'groq')):
            line.message_update({'body': '<p>Todo correcto, os esperamos.</p>'})
        log = self.env['restagrup.ai.log'].search([('source_model', '=', line._name), ('source_res_id', '=', line.id)])
        self.assertEqual(len(log), 1)
        self.assertFalse(log.activity_ids, 'el aviso ya no cuelga del registro interno de la IA')
        activities = lead.activity_ids.filtered(lambda a: 'revisa el presupuesto' in (a.summary or ''))
        self.assertEqual(activities.user_id, self.owner)
        log._close('confirmed')
        self.assertFalse(lead.activity_ids.filtered(lambda a: 'revisa el presupuesto' in (a.summary or '')))


@tagged('post_install', '-at_install')
class TestRonda2011Conversation(TransactionCase):
    """1b: el correo que sale al restaurante queda también en el Chatter del grupo. 1e: la elección de la agencia
    (con los platos que escribió) sale en la Conversación, no solo en el Chatter."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Ribs 2011', 'is_restaurant': True, 'email': 'ribs-2011@example.com', 'city': 'Madrid'})
        cls.menu = cls.env['restagrup.restaurant.menu'].create({
            'name': 'Menú 2011', 'partner_id': cls.restaurant.id, 'line_ids': [
                (0, 0, {'course': 'entrante', 'name': 'Sopa de fideos'}),
                (0, 0, {'course': 'principal', 'name': 'Pollo asado'})]})
        agency = cls.env['res.partner'].create({'name': 'Agencia conv 2011', 'is_company': True, 'email': 'a@conv.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo conv 2011', 'partner_id': agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 42})
        cls.line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'menu_id': cls.menu.id, 'etiqueta': 'presupuesto_recibido',
            'quote_price_pp': 14.0, 'quote_received_date': '2026-11-09 10:00:00'})

    def test_quote_request_text_is_in_the_group_chatter(self):
        self.line.action_request_quote(subject='Presupuesto para grupos 2011', body_text='Hola, ¿nos mandáis precio?')
        notes = self.lead.message_ids.filtered(lambda m: 'Presupuesto para grupos 2011' in (m.body or ''))
        self.assertTrue(notes, 'el asunto del correo enviado sale en el Chatter del grupo')
        self.assertIn('nos mandáis precio', notes[0].body)

    def test_agency_choice_shows_in_the_conversation(self):
        mails_before = self.env['mail.mail'].search_count([])
        self.lead._restagrup_portal_choose(self.search.id, self.line.id, '- Sopa de fideos\n- Pollo asado')
        self.assertEqual(self.env['mail.mail'].search_count([]), mails_before, 'no sale ningún correo')
        html = self.lead.restagrup_conversation_html
        self.assertIn('ha elegido', html)
        self.assertIn('Sopa de fideos', html)
        self.assertIn('o_rg_msg_agency', html)
        self.assertTrue(self.lead.message_ids.filtered(lambda m: 'ha elegido' in (m.body or '')),
                        'sigue saliendo en el Chatter')


@tagged('post_install', '-at_install')
class TestRonda2011MissingCourse(TransactionCase):
    """2a: si la agencia no elige plato de un tipo (p. ej. el postre) de un menú con varias opciones, se avisa."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa postres 2011', 'is_restaurant': True, 'email': 'postres-2011@example.com', 'city': 'Madrid'})
        agency = cls.env['res.partner'].create({'name': 'Agencia postres', 'is_company': True, 'email': 'a@p.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo postres 2011', 'partner_id': agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 30})

    def _line(self, courses):
        """Línea con presupuesto y un menú con los platos de `courses` {tipo: [platos]}."""
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú %s' % len(self.search.line_ids), 'partner_id': self.restaurant.id,
            'line_ids': [(0, 0, {'course': course, 'name': dish}) for course, dishes in courses.items()
                         for dish in dishes]})
        return self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'menu_id': menu.id, 'etiqueta': 'presupuesto_recibido',
            'quote_price_pp': 14.0, 'quote_received_date': '2026-11-09 10:00:00'})

    FULL = {'entrante': ['Sopa', 'Ensalada'], 'principal': ['Pollo', 'Lubina'], 'postre': ['Flan', 'Helado']}

    def test_missing_dessert_is_reported(self):
        line = self._line(self.FULL)
        line.agency_choice_notes = '- Sopa\n- Pollo'
        self.assertEqual(line._restagrup_missing_courses(), ['postre'])
        self.assertIn('postre', line._restagrup_dish_firewall_message())

    def test_all_courses_chosen_is_fine(self):
        line = self._line(self.FULL)
        line.agency_choice_notes = '- Sopa\n- Pollo\n- Flan'
        self.assertEqual(line._restagrup_missing_courses(), [])
        self.assertFalse(line._restagrup_dish_firewall_message())

    def test_a_course_with_a_single_dish_is_not_asked(self):
        line = self._line({'entrante': ['Sopa', 'Ensalada'], 'principal': ['Pollo', 'Lubina'], 'postre': ['Flan']})
        line.agency_choice_notes = '- Sopa\n- Pollo'
        self.assertEqual(line._restagrup_missing_courses(), [])

    def test_nothing_chosen_lists_every_course_with_options(self):
        line = self._line(self.FULL)
        self.assertEqual(line._restagrup_missing_courses(), ['entrante', 'principal', 'postre'])

    def test_portal_choice_without_dessert_leaves_a_note(self):
        line = self._line(self.FULL)
        self.lead._restagrup_portal_choose(self.search.id, line.id, '- Sopa\n- Pollo')
        note = self.lead.message_ids.filtered(lambda m: 'Falta elegir' in (m.body or ''))
        self.assertTrue(note)
        self.assertIn('postre', note[0].body)
