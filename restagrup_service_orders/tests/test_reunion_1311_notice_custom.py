# -*- coding: utf-8 -*-
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged

LINE = 'restagrup.restaurant.search.line'


@tagged('post_install', '-at_install')
class TestReunion1311NoticeCustom(TransactionCase):
    """Reunión 13/11 (P6): aviso a varios restaurantes con una plantilla común y, antes de enviar, el correo de un
    restaurante concreto retocado a mano. {evento} ya no repite los comensales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True))
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia común', 'email': 'comun@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo común', 'partner_id': cls.agency.id})
        cls.restaurants = cls.env['res.partner']
        for index, city in enumerate(('Málaga', 'Sevilla', 'Cádiz')):
            restaurant = cls.env['res.partner'].create({
                'name': 'Casa %s' % city, 'is_restaurant': True, 'email': 'casa%s@example.com' % index})
            cls.restaurants |= restaurant
            event = cls.env['restagrup.lead.event'].create({
                'lead_id': cls.lead.id, 'city': city, 'pax': 55, 'event_date': '2026-12-1%s' % index,
                'event_type_id': cls.env.ref('restagrup_core.event_type_lunch').id})
            search = cls.env['restagrup.restaurant.search'].create({
                'lead_id': cls.lead.id, 'event_id': event.id, 'city': city, 'min_capacity': 55})
            line = cls.env[LINE].create({
                'search_id': search.id, 'source': 'partner', 'name': restaurant.name, 'partner_id': restaurant.id,
                'etiqueta': 'presupuesto_recibido', 'quote_amount': 900})
            line.action_toggle_chosen()
            search.action_create_sale_order()

    def _wizard(self):
        wizard = self.lead._create_notice_wizard()
        wizard.write({'subject': 'Cambio {grupo}', 'body': '<p>Hola {restaurante}, ahora serán {comensales}.</p>'})
        return wizard

    def _line(self, wizard, restaurant):
        return wizard.line_ids.filtered(lambda line: line.restaurant_id == restaurant)

    def _sent(self):
        notices = self.env['restagrup.restaurant.notice'].search([('lead_id', '=', self.lead.id)])
        return {notice.restaurant_id: (notice.subject, notice.body) for notice in notices}

    def test_personalizing_a_row_fills_it_with_the_common_text_for_that_restaurant(self):
        wizard = self._wizard()
        with Form(wizard) as form:
            with form.line_ids.edit(0) as row:
                row.personalized = True
                self.assertEqual(row.custom_subject, 'Cambio Grupo común')
                self.assertIn('Hola %s' % wizard.line_ids[0].restaurant_id.name, row.custom_body)

    def test_one_custom_row_and_the_rest_with_the_common_text(self):
        wizard = self._wizard()
        special = self.restaurants[1]
        self._line(wizard, special).write({
            'personalized': True, 'custom_subject': 'Solo para ti', 'custom_body': '<p>Texto propio</p>'})
        wizard.action_send()
        sent = self._sent()
        self.assertEqual(set(sent), set(self.restaurants))
        self.assertEqual(sent[special][0], 'Solo para ti')
        self.assertIn('Texto propio', sent[special][1])
        for restaurant in self.restaurants - special:
            self.assertEqual(sent[restaurant][0], 'Cambio Grupo común')
            self.assertIn('Hola %s' % restaurant.name, sent[restaurant][1])

    def test_changing_the_common_text_keeps_the_custom_row(self):
        wizard = self._wizard()
        line = self._line(wizard, self.restaurants[0])
        line.write({'personalized': True, 'custom_subject': 'Propio', 'custom_body': '<p>Mío</p>'})
        wizard.write({'subject': 'Otro asunto', 'body': '<p>Otro texto</p>'})
        self.assertEqual(line.custom_subject, 'Propio')
        self.assertIn('Mío', line.custom_body)

    def test_unticking_personalized_goes_back_to_the_common_text(self):
        wizard = self._wizard()
        line = self._line(wizard, self.restaurants[0])
        line.write({'personalized': True, 'custom_subject': 'Propio', 'custom_body': '<p>Mío</p>'})
        line.personalized = False
        wizard.action_send()
        self.assertEqual(self._sent()[self.restaurants[0]][0], 'Cambio Grupo común')

    def test_firewall_reviews_the_final_text_of_each_restaurant(self):
        wizard = self._wizard()
        self._line(wizard, self.restaurants[2]).write({
            'personalized': True, 'custom_subject': 'Asunto revisado', 'custom_body': '<p>Cuerpo revisado</p>'})
        review = wizard._fw_review_restaurant_notice()
        self.assertIn('Asunto revisado', review)
        self.assertIn('Cuerpo revisado', review)
        self.assertIn('Hola Casa Málaga', review)

    def test_event_placeholder_does_not_repeat_the_diners(self):
        wizard = self._wizard()
        line = self._line(wizard, self.restaurants[0])
        _subject, body = line._render_notice('', '<p>{evento} · {comensales} comensales</p>')
        self.assertNotIn('pax', body)
        self.assertIn('Málaga', body)
        self.assertEqual(body.count('55'), 1)
