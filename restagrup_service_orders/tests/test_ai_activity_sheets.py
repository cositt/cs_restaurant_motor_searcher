# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM_PATH = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestAiActivitySheets(TransactionCase):
    """A4: la clasificación de la respuesta a una hoja de servicio queda registrada (informa, no se revisa)
    y avisa al responsable del presupuesto si la IA falla."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls.env['res.users'].create({'name': 'Comercial A4s', 'login': 'com_a4s', 'email': 'c4s@example.test'})
        agency = cls.env['res.partner'].create({'name': 'Agencia A4s', 'email': 'ag4s@example.com'})
        restaurant = cls.env['res.partner'].create({'name': 'Rest A4s', 'is_restaurant': True, 'email': 'r4s@example.com'})
        product = cls.env['product.product'].create({'name': 'Menú A4s', 'type': 'service'})
        order = cls.env['sale.order'].create({
            'partner_id': agency.id, 'user_id': cls.owner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 5, 'restaurant_id': restaurant.id})]})
        order.action_confirm()
        order.action_send_restaurant_orders()
        cls.po = order.sudo().restaurant_po_ids

    def _logs(self):
        return self.env['restagrup.ai.log'].search([
            ('kind', '=', 'sheet_classification'), ('source_model', '=', 'purchase.order'),
            ('source_res_id', '=', self.po.id)])

    def test_sheet_reply_classification_is_logged_as_automatic(self):
        with patch(LLM_PATH, return_value=({'estado': 'accepted', 'resumen': 'ok'}, 'groq')):
            self.po.message_update({'body': '<p>Confirmado.</p>'})
        self.assertEqual(self._logs().state, 'auto')

    def test_failed_classification_alerts_the_order_owner(self):
        with patch(LLM_PATH, return_value=(None, None)):
            self.po.message_update({'body': '<p>Confirmado.</p>'})
        log = self._logs()
        self.assertEqual(log.state, 'error')
        self.assertEqual(log.activity_ids.user_id, self.owner)
