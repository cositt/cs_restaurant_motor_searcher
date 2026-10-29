# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta

from lxml import etree

from odoo.tests.common import TransactionCase, tagged

REPLY_EMAIL = """Return-Path: <rest-guia@example.com>
To: restaurantes@restagrup.example.com
From: rest-guia@example.com
Subject: Re: {subject}
Message-Id: <reply-guia-1@example.com>
In-Reply-To: {parent}
References: {parent}
Content-Type: text/plain; charset=utf-8

Recibido, confirmamos el servicio.
"""


@tagged('post_install', '-at_install')
class TestGuiaProdFindings(TransactionCase):
    """Fallos vistos al probar la guía en producción (2026-10-29): hoja de servicio y fechas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, restagrup_skip_firewall=True, tz='Europe/Madrid'))
        cls.env.user.tz = 'Europe/Madrid'
        cls.env['ir.config_parameter'].sudo().search([('key', '=', 'restagrup.classify_incoming')]).unlink()
        cls.agency = cls.env['res.partner'].create({'name': 'Agencia guía', 'email': 'agencia-guia@example.com'})
        cls.restaurant = cls.env['res.partner'].create({
            'name': 'Restaurante guía', 'is_restaurant': True, 'email': 'rest-guia@example.com', 'lang': 'en_US',
        })
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo guía', 'partner_id': cls.agency.id})
        search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id, 'city': 'Málaga', 'min_capacity': 20,
        })
        line = cls.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'partner', 'name': cls.restaurant.name,
            'partner_id': cls.restaurant.id, 'etiqueta': 'presupuesto_recibido', 'quote_amount': 400,
        })
        line.action_toggle_chosen()
        search.action_create_sale_order()
        cls.order = search.sale_order_id
        cls.order.order_line.write({'service_date': date(2026, 11, 5), 'service_hour': 14.0})
        cls.order.action_confirm()
        cls.sheet = cls.order.restaurant_po_ids

    def _sheet_email(self):
        return self.sheet.message_ids.filtered(lambda m: m.message_type == 'email')

    # --- 5: la hoja queda en el hilo, en español, y la respuesta vuelve a ella ---

    def test_service_sheet_is_posted_on_the_sheet_thread_in_spanish(self):
        self.order.action_send_restaurant_orders()
        message = self._sheet_email()
        self.assertEqual(len(message), 1)
        self.assertIn('Hoja de servicio', message.subject)
        self.assertNotIn('Order', message.subject)
        self.assertTrue(message.attachment_ids, 'la hoja va en PDF')
        self.assertEqual(self.sheet.state, 'sent')

    def test_restaurant_reply_to_the_sheet_lands_on_the_sheet(self):
        self.order.action_send_restaurant_orders()
        message = self._sheet_email()
        raw = REPLY_EMAIL.format(subject=message.subject, parent=message.message_id)
        self.env['mail.thread'].message_process('restagrup.restaurant.search.line', raw)
        self.assertIn('confirmamos el servicio', ' '.join(self.sheet.message_ids.mapped('body')))

    # --- 6: enviar las hojas pide confirmación ---

    def test_send_sheets_button_asks_for_confirmation(self):
        arch = self.env['sale.order'].get_view(view_type='form')['arch']
        button = etree.fromstring(arch).xpath("//button[@name='action_send_restaurant_orders']")[0]
        self.assertTrue(button.get('confirm'))

    # --- 7: la hora de llegada es la hora local del servicio ---

    def test_planned_datetime_is_the_local_service_hour(self):
        planned = self.sheet.order_line[:1].date_planned
        # 5/11 en Madrid es UTC+1: las 14:00 locales son las 13:00 UTC.
        self.assertEqual(planned, datetime(2026, 11, 5, 13, 0))

    # --- 15: el cortafuegos de cierre mira también la fecha del pedido ---

    def test_close_check_uses_the_order_service_date(self):
        self.env['restagrup.lead.event'].create({
            'lead_id': self.lead.id, 'city': 'Málaga', 'event_date': date.today() - timedelta(days=3), 'pax': 20})
        self.order.order_line.write({'service_date': date.today() + timedelta(days=2)})
        self.assertTrue(self.lead._fw_service_done())

    def test_close_check_passes_when_order_service_is_over(self):
        self.order.order_line.write({'service_date': date.today() - timedelta(days=2)})
        self.assertFalse(self.lead._fw_service_done())

    # --- 13: la columna «Activo» del cortafuegos en español ---

    def test_firewall_active_column_is_in_spanish(self):
        self.assertEqual(self.env['restagrup.firewall.check']._fields['active'].string, 'Activo')

    # --- 7: las hojas ya creadas con la hora sin pasar a UTC se corrigen al actualizar ---

    def test_old_naive_planned_dates_are_fixed_once(self):
        line = self.sheet.order_line[:1]
        line.date_planned = datetime(2026, 11, 5, 14, 0)  # como se guardaba antes
        self.env['purchase.order.line']._restagrup_fix_naive_planned_dates()
        self.assertEqual(line.date_planned, datetime(2026, 11, 5, 13, 0))
        self.assertFalse(self.sheet.restagrup_needs_resend)
        self.env['purchase.order.line']._restagrup_fix_naive_planned_dates()
        self.assertEqual(line.date_planned, datetime(2026, 11, 5, 13, 0), 'no se corrige dos veces')
