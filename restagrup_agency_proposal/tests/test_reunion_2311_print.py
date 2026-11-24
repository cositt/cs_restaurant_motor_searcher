# -*- coding: utf-8 -*-
"""Reunión 23/11: un solo botón «Imprimir» con los cuatro PDF que genera Restagrup (propuesta/presupuesto,
confirmación a la agencia, confirmación al restaurante y bono), disponible en cualquier fase."""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

WIZARD = 'restagrup.print.wizard'
LEAD = 'odoo.addons.restagrup_agency_proposal.models.lead_documents.CrmLeadDocuments'


@tagged('post_install', '-at_install')
class TestReunion2311Print(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia imprimir', 'is_company': True, 'email': 'a@i.example'})
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo imprimir', 'partner_id': cls.agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Madrid', 'min_capacity': 20})

    def _wizard(self):
        action = self.lead.action_open_print_wizard()
        self.assertEqual(action['res_model'], WIZARD)
        self.assertEqual(action['target'], 'new')
        return self.env[WIZARD].browse(action['res_id'])

    def test_print_button_is_in_the_header_in_every_stage(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch'].split('</header>', 1)[0]
        self.assertIn('name="action_open_print_wizard"', arch)
        self.assertIn('Imprimir', arch)

    def test_print_replaces_the_three_download_buttons(self):
        arch = self.env['crm.lead'].get_view(view_type='form')['arch'].split('</header>', 1)[0]
        for name in ('action_download_agency_confirmation', 'action_download_restaurant_confirmation',
                     'action_download_voucher'):
            self.assertNotIn('name="%s"' % name, arch)

    def test_proposal_pdf_is_the_one_sent_to_the_agency(self):
        action = self._wizard().action_print_proposal()
        action = action.get('context', {}).get('report_action', action)
        self.assertEqual(action['report_name'], 'restagrup_agency_proposal.report_client_comparison')
        self.assertEqual(action['context']['active_ids'], self.search.ids)

    def test_proposal_pdf_without_searches_explains_what_is_missing(self):
        lead = self.env['crm.lead'].create({'name': 'Sin búsqueda'})
        wizard = self.env[WIZARD].browse(lead.action_open_print_wizard()['res_id'])
        with self.assertRaisesRegex(Exception, 'búsqueda'):
            wizard.action_print_proposal()

    def test_the_other_three_documents_use_the_file_downloads(self):
        wizard = self._wizard()
        for button, method in (('action_print_agency', 'action_download_agency_confirmation'),
                               ('action_print_restaurant', 'action_download_restaurant_confirmation'),
                               ('action_print_voucher', 'action_download_voucher')):
            with patch('%s.%s' % (LEAD, method), return_value={'sentinel': method}):
                self.assertEqual(getattr(wizard, button)(), {'sentinel': method})
