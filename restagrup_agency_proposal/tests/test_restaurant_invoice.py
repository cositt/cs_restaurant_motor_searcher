# -*- coding: utf-8 -*-
from collections import namedtuple
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'
Attachment = namedtuple('Attachment', ['fname', 'content', 'info'])
OUR_VAT = 'ESA00000000'


@tagged('post_install', '-at_install')
class TestRestaurantInvoice(TransactionCase):
    """F6: la factura de cada restaurante. Se reclama a los 1, 7, 15 y 30 días del servicio (la cuarta siempre la
    revisa una persona) y, cuando llega, la IA la lee y la comprueba; una persona la da por buena."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'approval')
        for template in cls.env['restagrup.mail.template'].search([]):
            template.auto_send = False
        cls.env.company.vat = OUR_VAT
        cls.Queue = cls.env['restagrup.pending.mail']
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia F6', 'email': 'f6@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Casa factura', 'is_restaurant': True, 'email': 'factura@example.com'})
        cls.product = cls.env['product.template'].create({
            'name': 'Menú factura', 'type': 'service', 'standard_price': 20.0, 'list_price': 25.0, 'sale_ok': True,
            'restaurant_id': cls.restaurant.id}).product_variant_id

    def _sheet(self, days_ago):
        lead = self.env['crm.lead'].create({'name': 'Grupo F6', 'partner_id': self.agency.id})
        order = self.env['sale.order'].create({
            'partner_id': self.agency.id, 'opportunity_id': lead.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 30, 'service_hour': 13.5,
                                   'service_date': fields.Date.context_today(lead) - timedelta(days=days_ago)})]})
        order.action_confirm()
        return order.restaurant_po_ids

    def _cron(self):
        self.env['purchase.order']._cron_restaurant_invoice_claims()

    def _claims(self, sheet):
        return self.Queue.search([('purchase_order_id', '=', sheet.id), ('kind', '=', 'restaurant_invoice_claim')])

    def _move(self, sheet, days_ago):
        sheet.order_line.restagrup_sale_line_id.service_date = fields.Date.context_today(sheet) - timedelta(days=days_ago)

    def _send_pending(self, sheet):
        self._claims(sheet).filtered(lambda m: m.state == 'pending').action_approve()

    # --- reclamar ---

    def test_nothing_on_the_day_of_the_service(self):
        sheet = self._sheet(0)
        self._cron()
        self.assertFalse(self._claims(sheet))

    def test_the_day_after_the_first_kind_request(self):
        sheet = self._sheet(1)
        self._cron()
        claim = self._claims(sheet)
        self.assertEqual(len(claim), 1)
        self.assertEqual(claim.invoice_claim_level, 1)
        self.assertEqual(claim.subject, 'Solicitud de factura del servicio Grupo F6')
        self.assertIn('Esperamos que todo haya ido genial', claim.body)
        self.assertIn(self.env.company.name, claim.body, 'datos fiscales')
        self.assertIn(OUR_VAT, claim.body)
        self.assertIn('30 pax', claim.body, 'datos de la reserva')

    def test_pax_is_the_menu_line_not_the_sum(self):
        sheet = self._sheet(1)
        sale_order = sheet.restagrup_sale_order_id
        sale_order.write({'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1})]})
        self.assertIn('30 pax', sheet._restagrup_booking_summary())
        self._cron()
        self.assertEqual(len(self._claims(sheet)), 1, 'una sola vez')

    def test_claims_escalate_at_seven_fifteen_and_thirty_days(self):
        sheet = self._sheet(1)
        for days, level, phrase in ((7, 2, 'aún no hemos recibido'), (15, 3, 'reconsiderar futuras colaboraciones'),
                                    (30, 4, 'Ley General Tributaria')):
            self._cron()
            self._send_pending(sheet)
            sheet.restagrup_invoice_claim_date = fields.Datetime.now() - timedelta(days=days)
            self._move(sheet, days)
            self._cron()
            claim = self._claims(sheet).filtered(lambda m: m.state == 'pending')
            self.assertEqual(claim.invoice_claim_level, level)
            self.assertIn(phrase, claim.body)
        self._send_pending(sheet)
        self.assertEqual(sheet.restagrup_invoice_claim_level, 4)
        self._move(sheet, 60)
        sheet.restagrup_invoice_claim_date = fields.Datetime.now() - timedelta(days=30)
        self._cron()
        self.assertFalse(self._claims(sheet).filtered(lambda m: m.state == 'pending'), 'no hay quinta')

    def test_a_late_sheet_starts_with_the_first_claim_and_waits_between_claims(self):
        sheet = self._sheet(20)
        self._cron()
        self.assertEqual(self._claims(sheet).invoice_claim_level, 1, 'nunca se empieza por la dura')
        self._send_pending(sheet)
        self._cron()
        self.assertFalse(self._claims(sheet).filtered(lambda m: m.state == 'pending'), 'espera entre reclamaciones')

    def test_old_sheets_are_not_claimed(self):
        sheet = self._sheet(90)
        self._cron()
        self.assertFalse(self._claims(sheet))

    def test_received_or_cancelled_invoices_are_not_claimed(self):
        received = self._sheet(1)
        received.action_mark_invoice_received()
        cancelled = self._sheet(1)
        cancelled.button_cancel()
        self._cron()
        self.assertFalse(self.Queue.search([('purchase_order_id', 'in', (received | cancelled).ids),
                                            ('kind', '=', 'restaurant_invoice_claim')]))

    def test_a_pending_claim_is_discarded_if_the_invoice_arrives(self):
        sheet = self._sheet(1)
        self._cron()
        sheet.action_mark_invoice_received()
        claim = self._claims(sheet)
        claim.action_approve()
        self.assertEqual(claim.state, 'discarded')

    def test_approving_sends_it_on_the_sheet_thread(self):
        sheet = self._sheet(1)
        self._cron()
        self._send_pending(sheet)
        sent = sheet.message_ids.filtered(lambda m: m.message_type == 'email')
        self.assertEqual(sent.outgoing_email_to, 'factura@example.com')
        self.assertEqual(sheet.restagrup_invoice_claim_level, 1)
        self.assertTrue(sheet.restagrup_invoice_claim_date)

    def test_first_claims_can_go_out_on_their_own(self):
        self.env['restagrup.mail.template']._get('restaurant_invoice_claim_1').auto_send = True
        sheet = self._sheet(1)
        self._cron()
        self.assertFalse(self._claims(sheet))
        self.assertEqual(sheet.restagrup_invoice_claim_level, 1)

    def test_the_fourth_claim_always_waits_for_a_person(self):
        self.env['ir.config_parameter'].sudo().set_param('restagrup.send_mode', 'automatic')
        sheet = self._sheet(30)
        sheet.write({'restagrup_invoice_claim_level': 3,
                     'restagrup_invoice_claim_date': fields.Datetime.now() - timedelta(days=15)})
        self._cron()
        claim = self._claims(sheet)
        self.assertEqual((claim.invoice_claim_level, claim.state), (4, 'pending'))

    def test_templates_exist(self):
        Template = self.env['restagrup.mail.template']
        for level in (1, 2, 3):
            self.assertTrue(Template._get('restaurant_invoice_claim_%s' % level).can_auto_send)
        self.assertFalse(Template._get('restaurant_invoice_claim_4').can_auto_send)

    # --- la factura ---

    def _reply(self, sheet, data, attachments=None):
        attachments = [Attachment('factura.pdf', b'x', {})] if attachments is None else attachments
        with patch(LLM_PATH, return_value=(data, 'groq')) as llm:
            sheet.message_update({'body': '<p>Adjuntamos factura.</p>', 'attachments': attachments})
        return llm

    def _invoice(self, sheet, **overrides):
        return dict({'es_factura': True, 'numero': 'F-2026-12', 'fecha': '2026-10-30',
                     'importe_total': sheet.amount_total, 'nif_receptor': OUR_VAT}, **overrides)

    def test_invoice_is_read_and_checked(self):
        sheet = self._sheet(2)
        self._reply(sheet, self._invoice(sheet))
        self.assertEqual(sheet.restagrup_invoice_proof_state, 'received')
        self.assertEqual(sheet.restagrup_invoice_number, 'F-2026-12')
        self.assertEqual(sheet.restagrup_invoice_amount, sheet.amount_total)
        self.assertEqual(sheet.restagrup_invoice_file_name, 'factura.pdf')
        self.assertFalse(sheet.restagrup_invoice_issues)
        self.assertFalse(sheet.restagrup_invoice_received, 'la da por buena una persona')

    def test_wrong_amount_or_tax_id_are_flagged(self):
        sheet = self._sheet(2)
        self._reply(sheet, self._invoice(sheet, importe_total=1.0, nif_receptor='B11111111'))
        self.assertIn('importe', sheet.restagrup_invoice_issues)
        self.assertIn('CIF', sheet.restagrup_invoice_issues)

    def test_invoice_without_number_is_flagged(self):
        sheet = self._sheet(2)
        self._reply(sheet, self._invoice(sheet, numero=None))
        self.assertIn('número', sheet.restagrup_invoice_issues)

    def test_tax_id_ignores_country_prefix_and_dashes(self):
        sheet = self._sheet(2)
        self._reply(sheet, self._invoice(sheet, nif_receptor='A-00000000'))
        self.assertFalse(sheet.restagrup_invoice_issues)

    def test_replies_without_attachments_do_not_ask_the_ai(self):
        sheet = self._sheet(2)
        llm = self._reply(sheet, self._invoice(sheet), attachments=[])
        self.assertFalse([c for c in llm.call_args_list if 'es_factura' in c.args[0]])
        self.assertFalse(sheet.restagrup_invoice_proof_state)

    def test_something_that_is_not_an_invoice_changes_nothing(self):
        sheet = self._sheet(2)
        self._reply(sheet, {'es_factura': False})
        self.assertFalse(sheet.restagrup_invoice_proof_state)

    def test_confirming_marks_it_received_and_stops_the_claims(self):
        sheet = self._sheet(1)
        self._reply(sheet, self._invoice(sheet))
        self._cron()
        self.assertFalse(self._claims(sheet), 'con factura por revisar no se reclama')
        sheet.action_confirm_restaurant_invoice()
        self.assertTrue(sheet.restagrup_invoice_received)
        self.assertFalse(sheet.restagrup_invoice_proof_state)
        self.assertEqual(sheet.restagrup_invoice_number, 'F-2026-12', 'el número se queda')

    def test_a_wrong_invoice_can_be_discarded_and_claims_resume(self):
        sheet = self._sheet(1)
        self._reply(sheet, self._invoice(sheet, importe_total=1.0))
        sheet.action_discard_restaurant_invoice()
        self.assertFalse(sheet.restagrup_invoice_proof_state)
        self._cron()
        self.assertTrue(self._claims(sheet))

    def test_sheet_form_shows_the_invoice(self):
        arch = self.env.ref('restagrup_agency_proposal.view_purchase_order_form_close_checklist').get_combined_arch()
        for name in ('restagrup_invoice_proof_state', 'action_confirm_restaurant_invoice',
                     'action_discard_restaurant_invoice', 'restagrup_invoice_claim_level'):
            self.assertIn(name, arch)
