# -*- coding: utf-8 -*-
"""Notas de Conchita tras la reunión del 05/11/2026 (bloque rápido: pantallas y textos).

- «Clientes» pasa a «Agencias»: fichas de agencia, junto a «Restaurantes».
- Ficha del restaurante: Menús lo primero y fuera lo que apenas usan.
- Expediente: «Añadir servicio» en vez de «Nuevo presupuesto», «Cancelar» en vez de «Rechazar presupuesto»
  y fuera los botones de la propuesta, que ya no tocan.
- Restaurante elegido a la vista: en la cabecera del grupo y en la lista de servicios.
- Numeración como su CRM: PET → PRE → EXP → TER.
"""
import re

from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


def _header(arch):
    return arch.split('</header>', 1)[0]


def _button(arch, **attrs):
    """Etiqueta <button …> de la cabecera que tiene todos los atributos dados."""
    for tag in re.findall(r'<button[^>]*>', _header(arch)):
        if all('%s="%s"' % (key, value) in tag for key, value in attrs.items()):
            return tag
    return None


def _pages(arch):
    return re.findall(r'<page[^>]*>', arch)


@tagged('post_install', '-at_install')
class TestReunion0511(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.agency = cls.env['res.partner'].create({'name': 'Viajes Monfragüe', 'is_company': True})
        cls.contact = cls.env['res.partner'].create({'name': 'Pilar Jaén', 'parent_id': cls.agency.id})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Tasquinha do Conselheiro', 'is_restaurant': True, 'is_company': True,
            'email': 'tasquinha@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo adultos', 'partner_id': cls.contact.id})
        cls.event = cls.env['restagrup.lead.event'].create({
            'lead_id': cls.lead.id, 'city': 'Braga', 'pax': 45, 'event_date': '2026-12-06',
            'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id,
        })
        cls.lead_arch = cls.env['crm.lead'].get_view(view_type='form')['arch']

    def _choose_restaurant(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'event_id': self.event.id, 'city': 'Braga', 'min_capacity': 45,
        })
        line = self.env[LINE].create({
            'search_id': search.id, 'source': 'partner', 'name': self.restaurant.name,
            'partner_id': self.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': 750,
        })
        line.action_toggle_chosen()
        return search

    # --- Agencias en lugar de Clientes ---

    def test_agencies_menu_replaces_clients(self):
        menu = self.env.ref('restagrup_service_orders.menu_restagrup_agencies')
        self.assertEqual(menu.name, 'Agencias')
        self.assertFalse(self.env.ref('restagrup_service_orders.menu_restagrup_clients', raise_if_not_found=False))

    def test_agencies_menu_is_right_before_restaurants(self):
        root = self.env.ref('restagrup_restaurants.menu_restagrup_root')
        siblings = root.child_id.sorted(lambda m: (m.sequence, m.id))
        names = siblings.mapped('name')
        self.assertEqual(names.index('Restaurantes'), names.index('Agencias') + 1)
        self.assertGreater(names.index('Agencias'), names.index('Terminados'))

    def test_agencies_action_lists_only_agencies(self):
        action = self.env['res.partner'].restagrup_action_agencies()
        self.assertEqual(action['res_model'], 'res.partner')
        found = self.env['res.partner'].search(action['domain'])
        self.assertIn(self.agency, found)
        self.assertNotIn(self.restaurant, found)
        self.assertNotIn(self.contact, found)
        self.assertNotIn(self.env.company.partner_id, found)
        self.assertTrue(action['context'].get('default_is_company'))

    # --- ficha del restaurante ---

    def test_restaurant_form_starts_with_menus(self):
        arch = self.env['res.partner'].get_view(self.env.ref('base.view_partner_form').id, 'form')['arch']
        names = [re.search(r'name="([^"]+)"', p).group(1) for p in _pages(arch)]
        self.assertEqual(names[:2], ['restaurant_menu_catalog', 'restaurant'])

    def test_restaurant_form_hides_little_used_pages(self):
        arch = self.env['res.partner'].get_view(self.env.ref('base.view_partner_form').id, 'form')['arch']
        pages = {re.search(r'name="([^"]+)"', p).group(1): p for p in _pages(arch)}
        for name in ('sales_purchases', 'accounting', 'geo_location', 'internal_notes', 'restaurant_menus'):
            self.assertIn('is_restaurant', pages[name], name)
        self.assertNotIn('is_restaurant', pages['contact_addresses'])

    # --- botones del expediente ---

    def test_new_quote_becomes_add_service_in_the_file(self):
        new_quote = _button(self.lead_arch, name='action_sale_quotations_new')
        self.assertIn('expediente', new_quote)
        add = _button(self.lead_arch, name='action_restagrup_add_service')
        self.assertIn('string="Añadir servicio"', add)
        self.assertIn("restagrup_stage_key != 'expediente'", add)

    def test_reject_becomes_cancel_in_the_file(self):
        reject = _button(self.lead_arch, string='Rechazar presupuesto')
        self.assertIn('expediente', reject)
        cancel = _button(self.lead_arch, string='Cancelar')
        self.assertIn("restagrup_stage_key != 'expediente'", cancel)
        action_id = re.search(r'name="(\d+)"', reject).group(1)
        self.assertIn('name="%s"' % action_id, cancel)  # el mismo asistente: pide motivo

    def test_proposal_buttons_are_gone_from_the_file(self):
        for name in ('action_open_proposal_wizard', 'action_create_joint_quote'):
            self.assertIn('expediente', _button(self.lead_arch, name=name), name)

    def test_add_service_opens_a_new_service_of_the_group(self):
        action = self.lead.action_restagrup_add_service()
        self.assertEqual(action['res_model'], 'restagrup.lead.event')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['default_lead_id'], self.lead.id)

    # --- restaurante elegido a la vista ---

    def test_service_shows_the_chosen_restaurant_next_to_its_state(self):
        self.assertFalse(self.event.chosen_restaurant_id)
        self._choose_restaurant()
        self.assertEqual(self.event.chosen_restaurant_id, self.restaurant)
        services = self.lead_arch.split('name="restagrup_events"', 1)[1].split('</page>', 1)[0]
        self.assertEqual(services.count('name="chosen_restaurant_id"'), 1)
        self.assertLess(services.index('name="chosen_restaurant_id"'), services.index('name="state"'))

    def test_group_header_shows_the_chosen_restaurants(self):
        sheet_top = self.lead_arch.split('<notebook', 1)[0]
        self.assertIn('name="restagrup_chosen_summary"', sheet_top)

    # --- numeración PET → PRE → EXP → TER ---

    def test_closed_files_use_ter(self):
        closed = self.env.ref('restagrup_service_orders.stage_cerrado')
        self.assertEqual(closed.restagrup_doc_prefix, 'TER')
        self.lead.stage_id = closed
        self.assertTrue(self.lead.restagrup_doc_number.startswith('TER'))
