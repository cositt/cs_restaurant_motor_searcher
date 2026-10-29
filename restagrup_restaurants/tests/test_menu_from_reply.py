# -*- coding: utf-8 -*-
import io
from collections import namedtuple
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
Attachment = namedtuple('Attachment', ['fname', 'content', 'info'])

MENU = {
    'nombre': 'Menú de paso', 'tipo': 'almuerzo', 'precio_persona': 17.6,
    'bebidas': 'Jarra de cerveza, agua, refresco, vino crianza',
    'platos': [
        {'tipo': 'entrante', 'nombre': 'Ensalada mixta'},
        {'tipo': 'entrante', 'nombre': 'Migas rondeñas'},
        {'tipo': 'principal', 'nombre': 'Carrillada a la rondeña'},
        {'tipo': 'postre', 'nombre': 'Postre casero'},
    ],
    'min_comensales': 20, 'max_comensales': 60,
}


@tagged('post_install', '-at_install')
class TestMenuFromReply(TransactionCase):
    """Si el restaurante manda un menú en su respuesta, la IA lo guarda en su ficha (con su precio) y lo deja
    asignado: nadie tiene que meterlo a mano."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.Menu = cls.env['restagrup.restaurant.menu']
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Mesón IA', 'is_restaurant': True, 'email': 'meson-ia@example.com'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo menú IA'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Ronda', 'min_capacity': 48})

    def _line(self, partner=True):
        return self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'partner' if partner else 'google', 'name': 'Mesón IA',
            'partner_id': self.restaurant.id if partner else False, 'email': 'meson-ia@example.com',
            'etiqueta': 'solicitado'})

    def _reply(self, line, menus, importe=850.0, attachments=None, body='<p>Os mandamos el menú.</p>'):
        with patch(LLM_PATH, return_value=({'importe': importe, 'notas': None, 'menus': menus}, 'groq')) as llm:
            line.message_update({'body': body, 'attachments': attachments or []})
        return llm

    def _menus(self):
        return self.Menu.search([('partner_id', '=', self.restaurant.id)])

    # --- crear el menú ---

    def test_menu_in_the_reply_is_saved_on_the_restaurant(self):
        line = self._line()
        self._reply(line, [MENU])
        menu = self._menus()
        self.assertEqual(len(menu), 1)
        self.assertEqual(menu.name, 'Menú de paso')
        self.assertEqual(menu.menu_type, 'almuerzo')
        self.assertEqual(menu.cost_price, 17.6, 'lo que cobra el restaurante es nuestro coste')
        self.assertGreater(menu.sale_price, menu.cost_price, 'el precio de venta sale con el margen')
        self.assertTrue(menu.drinks_included)
        self.assertEqual(menu.drinks_description, 'Jarra de cerveza, agua, refresco, vino crianza')
        self.assertEqual((menu.min_pax, menu.max_pax), (20, 60))
        self.assertEqual(menu.line_ids.mapped('name'),
                         ['Ensalada mixta', 'Migas rondeñas', 'Carrillada a la rondeña', 'Postre casero'])
        self.assertEqual(set(menu.line_ids.mapped('course')), {'entrante', 'principal', 'postre'})
        self.assertEqual(menu.season, fields.Date.context_today(menu).year)

    def test_created_menu_is_marked_for_review_and_traced_to_the_reply(self):
        line = self._line()
        self._reply(line, [MENU])
        menu = self._menus()
        self.assertTrue(menu.ai_pending_review)
        self.assertEqual(menu.source_line_id, line)
        menu.action_mark_reviewed()
        self.assertFalse(menu.ai_pending_review)

    def test_menu_is_assigned_to_the_line(self):
        line = self._line()
        self._reply(line, [MENU])
        self.assertEqual(line.menu_id, self._menus())

    def test_a_menu_already_chosen_on_the_line_is_not_replaced(self):
        line = self._line()
        chosen = self.Menu.create({'name': 'Elegido a mano', 'partner_id': self.restaurant.id, 'cost_price': 20})
        line.menu_id = chosen
        self._reply(line, [MENU])
        self.assertEqual(line.menu_id, chosen)

    def test_several_menus_create_several_records(self):
        line = self._line()
        dinner = dict(MENU, nombre='Menú cena', tipo='cena', precio_persona=24.0)
        self._reply(line, [MENU, dinner])
        self.assertEqual(set(self._menus().mapped('name')), {'Menú de paso', 'Menú cena'})

    def test_reply_without_menu_creates_nothing(self):
        line = self._line()
        self._reply(line, [])
        self.assertFalse(self._menus())
        self.assertEqual(line.quote_amount, 850.0, 'el importe se sigue leyendo como siempre')

    def test_result_without_restaurant_contact_becomes_a_contact_with_the_menu(self):
        line = self._line(partner=False)
        self._reply(line, [MENU])
        self.assertTrue(line.partner_id, 'el restaurante pasa a ser contacto')
        self.assertTrue(line.partner_id.is_restaurant)
        self.assertEqual(line.partner_id.email, 'meson-ia@example.com')
        menu = self.Menu.search([('partner_id', '=', line.partner_id.id)])
        self.assertEqual(menu.name, 'Menú de paso')
        self.assertEqual(line.menu_id, menu)
        self.assertIn('añadido como contacto', ' '.join(self.search.message_ids.mapped('body')))

    def test_result_without_contact_reuses_the_existing_one(self):
        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': self.search.id, 'source': 'google', 'name': 'Mesón IA', 'email': 'meson-ia@example.com',
            'google_place_id': 'place-meson-ia', 'phone': '+34 600 000 000', 'etiqueta': 'solicitado'})
        self.restaurant.restaurant_google_place_id = 'place-meson-ia'
        self._reply(line, [MENU])
        self.assertEqual(line.partner_id, self.restaurant, 'no se duplica el contacto')

    def test_unknown_menu_type_and_course_fall_back_safely(self):
        line = self._line()
        odd = dict(MENU, tipo='merienda', platos=[{'tipo': 'tapa', 'nombre': 'Croquetas'}])
        self._reply(line, [odd])
        menu = self._menus()
        self.assertEqual(menu.menu_type, 'sin_definir')
        self.assertEqual(menu.line_ids.course, 'otro')

    # --- menú parecido ---

    def test_similar_menu_creates_a_new_one_with_its_date_and_warns(self):
        old = self.Menu.create({'name': 'Menú de paso', 'partner_id': self.restaurant.id, 'cost_price': 16.0})
        line = self._line()
        self._reply(line, [MENU])
        new = self._menus() - old
        self.assertEqual(len(new), 1)
        self.assertIn(fields.Date.context_today(new).strftime('%d/%m/%Y'), new.name)
        self.assertEqual(new.similar_menu_id, old)
        self.assertEqual(old.cost_price, 16.0, 'el que había no se toca')
        self.assertIn('parecido', ' '.join(self.search.message_ids.mapped('body')))

    def test_identical_menu_is_reused_not_duplicated(self):
        line = self._line()
        self._reply(line, [MENU])
        first = self._menus()
        other = self._line()
        self._reply(other, [MENU])
        self.assertEqual(self._menus(), first)
        self.assertEqual(other.menu_id, first)

    def test_similar_name_ignores_accents_and_case(self):
        old = self.Menu.create({'name': 'MENU DE PASO', 'partner_id': self.restaurant.id, 'cost_price': 16.0})
        self._reply(self._line(), [MENU])
        self.assertEqual((self._menus() - old).similar_menu_id, old)

    # --- adjuntos ---

    def test_pdf_attachment_text_is_read_too(self):
        content = self._pdf_with_text()
        line = self._line()
        llm = self._reply(line, [MENU], attachments=[Attachment('menu.pdf', content, {})])
        sent = llm.call_args.args[1]
        self.assertIn('menu.pdf', sent)

    def _pdf_with_text(self):
        # PDF mínimo válido con una línea de texto.
        objects = [
            b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R'
            b' /Resources << /Font << /F1 5 0 R >> >> >>',
            None,
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        ]
        stream = b'BT /F1 12 Tf 20 100 Td (Menu de paso 17,60) Tj ET'
        objects[3] = b'<< /Length %d >>\nstream\n%s\nendstream' % (len(stream), stream)
        out = io.BytesIO()
        out.write(b'%PDF-1.4\n')
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(out.tell())
            out.write(b'%d 0 obj\n%s\nendobj\n' % (number, body))
        xref = out.tell()
        out.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1))
        for offset in offsets:
            out.write(b'%010d 00000 n \n' % offset)
        out.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF' % (len(objects) + 1, xref))
        return out.getvalue()

    def test_pdf_text_reaches_the_ai(self):
        line = self._line()
        llm = self._reply(line, [MENU], attachments=[Attachment('menu.pdf', self._pdf_with_text(), {})])
        self.assertIn('Menu de paso 17,60', llm.call_args.args[1])

    def test_broken_attachment_does_not_stop_the_reply(self):
        line = self._line()
        self._reply(line, [MENU], attachments=[Attachment('roto.pdf', b'no es un pdf', {})])
        self.assertEqual(line.quote_amount, 850.0)

    # --- datos que faltan en la respuesta ---

    def test_menu_without_price_drinks_or_dessert_asks_the_restaurant(self):
        line = self._line()
        incomplete = dict(MENU, precio_persona=None, bebidas=None,
                          platos=[{'tipo': 'principal', 'nombre': 'Carrillada'}])
        self._reply(line, [incomplete], importe=None)
        mail = self.Queue.search([('line_id', '=', line.id), ('kind', '=', 'quote_incomplete')])
        self.assertEqual(len(mail), 1)
        for label in ('Precio por persona', 'Bebidas', 'Postre'):
            self.assertIn(label, mail.body)
        self.assertIn('salvo error, faltaría saber', mail.body)

    def test_complete_menu_asks_nothing(self):
        line = self._line()
        self._reply(line, [MENU])
        self.assertFalse(self.Queue.search([('line_id', '=', line.id), ('kind', '=', 'quote_incomplete')]))

    def test_incomplete_request_is_not_repeated(self):
        line = self._line()
        incomplete = dict(MENU, bebidas=None)
        self._reply(line, [incomplete])
        self._reply(line, [incomplete])
        self.assertEqual(len(self.Queue.search([('line_id', '=', line.id), ('kind', '=', 'quote_incomplete')])), 1)

    def test_incomplete_request_can_go_out_on_its_own(self):
        self.env['restagrup.mail.template']._get('quote_incomplete').auto_send = True
        line = self._line()
        self._reply(line, [dict(MENU, bebidas=None)])
        self.assertFalse(self.Queue.search([('line_id', '=', line.id), ('kind', '=', 'quote_incomplete')]))
        self.assertTrue(line.message_ids.filtered(lambda m: m.message_type == 'email'))

    def test_approving_the_incomplete_request_writes_to_the_restaurant(self):
        line = self._line()
        self._reply(line, [dict(MENU, bebidas=None)])
        mail = self.Queue.search([('line_id', '=', line.id), ('kind', '=', 'quote_incomplete')])
        mail.action_approve()
        self.assertEqual(mail.state, 'sent')
        sent = line.message_ids.filtered(lambda m: m.message_type == 'email')
        self.assertEqual(sent.outgoing_email_to, 'meson-ia@example.com')

    # --- en pantalla ---

    def test_menu_screens_show_the_review_state(self):
        form = self.env.ref('restagrup_restaurants.view_restaurant_menu_form').get_combined_arch()
        self.assertIn('action_mark_reviewed', form)
        self.assertIn('similar_menu_id', form)
        search = self.env.ref('restagrup_restaurants.view_restaurant_menu_search').get_combined_arch()
        self.assertIn('ai_pending_review', search)
