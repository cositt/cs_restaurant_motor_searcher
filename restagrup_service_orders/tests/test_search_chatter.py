# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

LLM = 'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json'


@tagged('post_install', '-at_install')
class TestSearchChatter(TransactionCase):
    """El chatter de la búsqueda cuenta todo el ciclo: pedido, hojas, cambios y respuestas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia Chatter', 'email': 'agencia@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante Chatter', 'is_restaurant': True, 'email': 'rest@example.com',
        })
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo chatter', 'partner_id': cls.agency.id})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Marbella', 'min_capacity': 15,
        })
        line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': cls.search.id, 'source': 'partner', 'name': 'Restaurante Chatter',
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': 300,
        })
        line.action_toggle_chosen()
        cls.search.action_create_sale_order()
        cls.order = cls.search.sale_order_id

    def _log(self):
        self.search.invalidate_recordset(['message_ids'])
        return ' '.join(str(body) for body in self.search.message_ids.mapped('body'))

    def test_sale_order_creation_is_logged_on_search(self):
        self.assertIn(self.order.name, self._log())

    def test_order_confirmation_is_logged_on_search(self):
        self.order.action_confirm()
        self.assertIn('confirmado', self._log().lower())
        self.assertIn(self.order.name, self._log())

    def test_sending_service_sheets_is_logged_on_search(self):
        self.order.action_confirm()
        self.order.action_send_restaurant_orders()
        self.assertIn('Hoja de servicio enviada', self._log())
        self.assertIn('Restaurante Chatter', self._log())

    def test_resending_changes_is_logged_on_search_with_agency_notice(self):
        self.order.action_confirm()
        self.order.action_send_restaurant_orders()
        self.order.order_line[0].product_uom_qty = 18
        self.order.action_resend_restaurant_orders()
        log = self._log()
        self.assertIn('Cambios reenviados', log)
        self.assertIn('Restaurante Chatter', log)
        self.assertIn('agencia', log.lower())

    def test_service_sheet_reply_is_logged_on_search(self):
        self.order.action_confirm()
        self.order.action_send_restaurant_orders()
        po = self.order.restaurant_po_ids
        with patch(LLM, return_value=({'estado': 'accepted', 'resumen': 'Reserva confirmada para 15'}, 'groq')):
            po._restagrup_classify_response({'body': '<p>Confirmamos la reserva.</p>'})
        log = self._log()
        self.assertIn('Restaurante Chatter', log)
        self.assertIn('Reserva confirmada para 15', log)
