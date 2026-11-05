# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.restagrup_demo3.models.demo_simulate import SERVICE_IN_DAYS, _pdf

EXTRACT = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
INCOMPLETE = {'agencia': 'Costa Viajes Ibéricos', 'ciudad': 'Sevilla', 'num_pax': 45, 'fecha_servicio': None, 'tipo_grupo': 'senior',
              'eventos': [{'ciudad': 'Sevilla', 'fecha': None, 'pax': 45, 'tipo': 'comida', 'notas': ''}]}
PRICES = {'Taberna del Patio Andaluz': 26.0, 'Casa Giralda Grupos': 28.0, 'Bodega San Telmo': 24.5}


@tagged('post_install', '-at_install')
class TestDemo3Guide(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.guide = cls.env['restagrup.demo3.guide']
        cls.guide.reset_demo()  # independiente de lo que haya en la BD (todo se deshace al acabar el test)
        cls.env.company.vat = 'ESB93000008'
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        cls.restaurants = {}
        for name, price in PRICES.items():
            partner = cls.env['res.partner'].search([('name', '=', name), ('is_restaurant', '=', True)], limit=1)
            if not partner:
                partner = cls.env['res.partner'].create({
                    'name': name, 'is_restaurant': True, 'city': 'Sevilla',
                    'email': 'reservas@%s.demo' % name.split()[0].lower()})
            partner.bank_ids.unlink()
            cls.env['restagrup.restaurant.menu'].create({
                'name': 'Menú 2026', 'partner_id': partner.id, 'season': 2026, 'cost_price': price,
                'description': 'Entrantes, principal, postre y bebidas incluidas.'})
            cls.restaurants[name] = partner

    # --- ayudas ---

    def _pending(self, **domain):
        return self.env['restagrup.pending.mail'].search([(key, '=', value) for key, value in domain.items()])

    def _completed_lead(self):
        with patch(EXTRACT, return_value=(INCOMPLETE, 'groq')):
            lead = self.env['crm.lead'].browse(self.guide.simulate_agency_email())
        self._pending(request_lead_id=lead.id).action_approve()
        day = fields.Date.today() + timedelta(days=SERVICE_IN_DAYS)
        reply = {'eventos': [{'id': lead.restagrup_event_ids[:1].id, 'fecha': str(day), 'hora': '14:00'}]}
        with patch(EXTRACT, return_value=(reply, 'groq')):
            self.guide.simulate_agency_reply()
        return lead

    def _quoted_search(self):
        lead = self._completed_lead()
        search = self.env['restagrup.restaurant.search'].create(
            {'lead_id': lead.id, 'city': 'Sevilla', 'min_capacity': 45, 'event_id': lead.restagrup_event_ids[:1].id})
        for name, partner in self.restaurants.items():
            self.env['restagrup.restaurant.search.line'].create({
                'search_id': search.id, 'source': 'partner', 'name': name, 'partner_id': partner.id,
                'email': partner.email})
        self.guide.request_quotes()
        replies = [({'importe': price * 45, 'notas': 'Menú de grupo'}, 'groq') for price in PRICES.values()]
        with patch(EXTRACT, side_effect=replies + [({}, 'groq')] * 6):
            self.guide.simulate_restaurant_replies()
        self.guide.confirm_quotes()
        return lead, search

    def _signed(self):
        lead, search = self._quoted_search()
        search.line_ids.sorted('quote_amount')[:1].action_toggle_chosen()
        search.action_create_sale_order()
        order = search.sale_order_id
        order.action_confirm()
        self.guide.apply_gratuities()
        return lead, order

    def _sheet_sent_and_accepted(self):
        lead, order = self._signed()
        order.action_send_restaurant_orders()
        with patch(EXTRACT, return_value=({'estado': 'accepted', 'resumen': 'Confirma la reserva'}, 'groq')):
            self.guide.simulate_restaurant_confirmation()
        return lead, order, self.guide._rg_sheet(order)

    def _payments_approved(self):
        lead, order, sheet = self._sheet_sent_and_accepted()
        self.guide.run_daily_checks()
        self._pending(sale_order_id=order.id, kind='agency_payment_request').action_approve()
        self._pending(purchase_order_id=sheet.id, kind='restaurant_bank_request').action_approve()
        return lead, order, sheet

    # --- petición ---

    def test_agency_reply_gives_a_date_within_the_payment_window(self):
        lead = self._completed_lead()
        reply = lead.message_ids.filtered(lambda m: (m.subject or '').startswith('Re: Datos'))[:1]
        self.assertTrue(reply)
        self.assertIn('14:00', reply.body)
        state = self.guide.get_state()['done']
        self.assertTrue(state['reply'])
        self.assertFalse(state['assign'])

    def test_assigning_a_salesperson_completes_the_step(self):
        lead = self._completed_lead()
        lead.user_id = self.env.user
        self.assertTrue(self.guide.get_state()['done']['assign'])

    def test_reply_needs_the_request_to_be_sent_first(self):
        with patch(EXTRACT, return_value=(INCOMPLETE, 'groq')):
            self.guide.simulate_agency_email()
        with self.assertRaises(UserError):
            self.guide.simulate_agency_reply()

    # --- restaurantes ---

    def test_restaurant_replies_bring_their_menu_and_the_quotes_get_confirmed(self):
        lead, search = self._quoted_search()
        bodies = ' '.join(search.line_ids.message_ids.mapped('body'))
        self.assertIn('Menú Senior San Telmo', bodies)
        self.assertEqual(set(search.line_ids.mapped('etiqueta')), {'presupuesto_recibido'})
        self.assertTrue(all(search.line_ids.mapped('menu_id')))
        done = self.guide.get_state()['done']
        self.assertTrue(done['answers'] and done['menu_review'] and done['confirm'])

    def test_menus_created_by_the_ai_must_be_reviewed(self):
        lead, search = self._quoted_search()
        menu = self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú IA', 'partner_id': self.restaurants['Bodega San Telmo'].id, 'season': 2026,
            'cost_price': 24.5, 'ai_pending_review': True})
        self.assertFalse(self.guide.get_state()['done']['menu_review'])
        menu.ai_pending_review = False
        self.assertTrue(self.guide.get_state()['done']['menu_review'])

    # --- expediente ---

    def test_restaurant_confirms_the_service_sheet(self):
        lead, order, sheet = self._sheet_sent_and_accepted()
        self.assertEqual(sheet.restagrup_response_state, 'accepted')
        done = self.guide.get_state()['done']
        self.assertTrue(done['sheets_sent'] and done['restaurant_ok'])

    def test_confirmation_needs_the_sheet_sent(self):
        self._signed()
        with self.assertRaises(UserError):
            self.guide.simulate_restaurant_confirmation()

    # --- pagos ---

    def test_daily_checks_queue_the_payment_and_bank_requests(self):
        lead, order, sheet = self._sheet_sent_and_accepted()
        self.guide.run_daily_checks()
        self.assertTrue(self._pending(sale_order_id=order.id, kind='agency_payment_request'))
        self.assertTrue(self._pending(purchase_order_id=sheet.id, kind='restaurant_bank_request'))
        self.assertTrue(self.guide.get_state()['done']['daily'])

    def test_proof_needs_the_payment_request_approved(self):
        self._sheet_sent_and_accepted()
        self.guide.run_daily_checks()
        with self.assertRaises(UserError):
            self.guide.simulate_agency_payment_proof()

    def test_agency_proof_is_read_and_a_person_confirms_it(self):
        lead, order, sheet = self._payments_approved()
        self.assertTrue(self.guide.get_state()['done']['payments_sent'])
        with patch(EXTRACT, return_value=({'es_justificante': True, 'importe': order.amount_total}, 'groq')):
            self.guide.simulate_agency_payment_proof()
        self.assertEqual(order.restagrup_payment_proof_state, 'received')
        self.assertFalse(order.restagrup_paid)  # nunca se marca pagado solo
        order.action_confirm_payment_proof()
        self.assertTrue(self.guide.get_state()['done']['agency_paid'])

    def test_restaurant_iban_is_saved_in_its_card(self):
        lead, order, sheet = self._payments_approved()
        self.guide.simulate_restaurant_bank()
        self.assertTrue(sheet.restagrup_has_bank)
        sheet.action_mark_restaurant_paid()
        self.assertTrue(self.guide.get_state()['done']['restaurant_paid'])

    # --- cierre ---

    def test_service_done_queues_the_first_invoice_claim(self):
        lead, order, sheet = self._payments_approved()
        self.guide.simulate_service_done()
        yesterday = fields.Date.today() - timedelta(days=1)
        self.assertEqual(sheet.restagrup_service_end_date, yesterday)
        claim = self._pending(purchase_order_id=sheet.id, kind='restaurant_invoice_claim')
        self.assertEqual(claim.invoice_claim_level, 1)
        self.assertTrue(self.guide.get_state()['done']['service_done'])

    def test_service_done_moves_the_sheet_too_without_asking_the_restaurant_again(self):
        """Adelantar la fecha es un truco de la demo, no un cambio real: la hoja no queda con cambios por
        reenviar ni vuelve a pedir confirmación al restaurante."""
        lead, order, sheet = self._payments_approved()
        self.guide.simulate_service_done()
        self.assertFalse(sheet.restagrup_needs_resend)
        self.assertFalse(order.restaurant_changes_pending)
        self.assertEqual(sheet.restagrup_response_state, 'accepted')
        yesterday = fields.Date.today() - timedelta(days=1)
        self.assertEqual(sheet.order_line.filtered('restagrup_sale_line_id')[:1].date_planned.date(), yesterday)

    def test_full_close(self):
        lead, order, sheet = self._payments_approved()
        with patch(EXTRACT, return_value=({'es_justificante': True, 'importe': order.amount_total}, 'groq')):
            self.guide.simulate_agency_payment_proof()
        order.action_confirm_payment_proof()
        self.guide.simulate_restaurant_bank()
        sheet.action_mark_restaurant_paid()
        self.guide.simulate_service_done()
        self._pending(purchase_order_id=sheet.id, kind='restaurant_invoice_claim').action_approve()
        invoice = {'es_factura': True, 'numero': 'F-2026-0153', 'fecha': str(fields.Date.today()),
                   'importe_total': sheet.amount_total, 'nif_receptor': 'B93000008'}
        with patch(EXTRACT, return_value=(invoice, 'groq')):
            self.guide.simulate_restaurant_invoice()
        self.assertEqual(sheet.restagrup_invoice_proof_state, 'received')
        self.assertFalse(sheet.restagrup_invoice_issues)  # cuadra con la hoja y lleva nuestro CIF
        sheet.action_confirm_restaurant_invoice()
        with self.assertRaises(UserError):  # cortafuegos: falta la factura a la agencia
            lead.action_close_file()
        order.action_mark_invoice_sent()
        lead.action_close_file()
        self.assertEqual(lead.restagrup_stage_key, 'cerrado')
        self.assertTrue(self.guide.get_state()['done']['closed'])

    # --- documentos, reinicio y llamadas del navegador ---

    def test_pdf_text_is_readable(self):
        from odoo.addons.restagrup_restaurants.models.restaurant_menu_ai import _attachment_text
        text = _attachment_text([('Factura.pdf', _pdf('FACTURA F-1', ['Total factura: 10,00 EUR']))])
        self.assertIn('Total factura: 10,00 EUR', text)

    def test_reset_removes_the_walkthrough_ai_menus_and_bank_accounts(self):
        other = self.env['crm.lead'].create({'name': 'Documento de ejemplo'})
        lead, order, sheet = self._payments_approved()
        self.guide.simulate_restaurant_bank()
        self.env['restagrup.restaurant.menu'].create({
            'name': 'Menú IA', 'partner_id': self.restaurants['Bodega San Telmo'].id, 'season': 2026,
            'cost_price': 24.5, 'ai_pending_review': True})
        self.guide.mark_seen('control')
        self.guide.reset_demo()
        self.assertFalse(self.guide._lead())
        self.assertFalse(self.env['res.partner.bank'].search(
            [('partner_id', 'in', [p.id for p in self.restaurants.values()])]))
        self.assertFalse(self.env['restagrup.restaurant.menu'].search([('ai_pending_review', '=', True),
            ('partner_id', 'in', [p.id for p in self.restaurants.values()])]))
        self.assertTrue(other.exists())
        self.assertFalse(any(self.guide.get_state()['done'].values()))

    def test_every_method_the_browser_calls_works_without_records(self):
        """El JS llama orm.call(GUIDE, method, args) sin ids: si un método pierde @api.model, call_kw falla."""
        methods = ['get_state', 'reset_demo', 'mark_seen', 'simulate_agency_email', 'simulate_agency_reply',
                   'request_quotes', 'simulate_restaurant_replies', 'confirm_quotes', 'apply_gratuities',
                   'simulate_restaurant_confirmation', 'run_daily_checks', 'simulate_agency_payment_proof',
                   'simulate_restaurant_bank', 'simulate_service_done', 'simulate_restaurant_invoice']
        model = type(self.env['restagrup.demo3.guide'])
        for name in methods:
            self.assertTrue(getattr(getattr(model, name), '_api_model', False), name)

    # --- cambios de la PPT de Conchita (2026-11-04) que enseña la demo ---

    def test_agency_email_brings_a_group_reference_and_a_full_signature(self):
        """Diapositivas 1.2 y 2.1: la referencia del grupo da el título y la firma completa la ficha de la agencia."""
        from odoo.addons.restagrup_demo3.models.demo_simulate import AGENCY_BODY_HTML, AGENCY_REFERENCE
        for text in (AGENCY_REFERENCE, 'Tel. 952 000 000', '29005 Málaga', 'www.costaviajes.demo'):
            self.assertIn(text, AGENCY_BODY_HTML)
        extracted = dict(INCOMPLETE, agencia='Costa Viajes Ibéricos', referencia_grupo=AGENCY_REFERENCE, firma={
            'nombre': 'Lucía Prieto', 'telefono': '952 000 000', 'direccion': 'Calle Larios 12',
            'codigo_postal': '29005', 'ciudad': 'Málaga', 'web': 'www.costaviajes.demo'})
        with patch(EXTRACT, return_value=(extracted, 'groq')):
            lead = self.env['crm.lead'].browse(self.guide.simulate_agency_email())
        self.assertEqual(lead.name, AGENCY_REFERENCE)
        agency = lead.partner_id.commercial_partner_id
        self.assertEqual(agency.name, 'Costa Viajes Ibéricos')
        self.assertEqual((agency.phone, agency.zip, agency.city), ('952 000 000', '29005', 'Málaga'))

    def test_signing_queues_the_fiscal_data_request_and_reset_removes_it(self):
        """Diapositiva 2.2: al firmar, la petición del CIF y la razón social a la agencia va a la cola."""
        lead, order = self._signed()
        self.assertTrue(self._pending(request_lead_id=lead.id, kind='agency_fiscal_request'))
        self.guide.reset_demo()
        self.assertFalse(self.env['restagrup.pending.mail'].search([('kind', '=', 'agency_fiscal_request'),
                                                                     ('recipient_email', 'ilike', 'costaviajes')]))

    def test_reset_also_removes_the_invoices_made_from_the_quote(self):
        """Si en el recorrido se crea la factura a la agencia (borrador o validada), el reinicio no se bloquea."""
        lead, order = self._signed()
        invoices = order._create_invoices()
        invoices.action_post()
        self.guide.reset_demo()
        self.assertFalse(invoices.exists())
        self.assertFalse(self.guide._lead())

    def test_steps_point_out_what_changed(self):
        """La guía marca «Nuevo» en los pasos que cambian con la PPT y lo muestra siempre, no solo en las notas."""
        from odoo.modules.module import get_module_path
        import os
        base = os.path.join(get_module_path('restagrup_demo3'), 'static', 'src', 'js')
        steps = open(os.path.join(base, 'steps.js'), encoding='utf-8').read()
        self.assertGreaterEqual(steps.count('news: ['), 12)
        self.assertNotIn('Buscar para todos los eventos', steps)
        self.assertNotIn('pestaña Eventos', steps)
        template = open(os.path.join(base, 'guide.xml'), encoding='utf-8').read()
        self.assertIn('step.news', template)
        self.assertIn('CHANGES', open(os.path.join(base, 'guide.js'), encoding='utf-8').read())
