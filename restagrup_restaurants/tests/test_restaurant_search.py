# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.fields import Datetime
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRestaurantSearch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['crm.lead'].create({'name': 'Grupo de prueba'})
        cls.search = cls.env['restagrup.restaurant.search'].create({
            'lead_id': cls.lead.id,
            'city': 'Madrid',
            'min_capacity': 20,
        })

    def _create_line(self, **vals):
        defaults = {
            'search_id': self.search.id,
            'source': 'google',
            'name': 'Restaurante Test',
        }
        defaults.update(vals)
        return self.env['restagrup.restaurant.search.line'].create(defaults)

    # --- _search_partners: ciudad/CP/calle como campos independientes ---

    def test_search_partners_filters_by_city(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        matching = self.env['res.partner'].create({
            'name': 'Restaurante Madrid', 'is_restaurant': True, 'city': 'Madrid',
        })
        other = self.env['res.partner'].create({
            'name': 'Restaurante Sevilla', 'is_restaurant': True, 'city': 'Sevilla',
        })
        found = search._search_partners()
        self.assertIn(matching, found)
        self.assertNotIn(other, found)

    def test_search_partners_filters_by_zip_and_street(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid', 'zip': '28001', 'street': 'Serrano',
        })
        matching = self.env['res.partner'].create({
            'name': 'Con CP', 'is_restaurant': True, 'city': 'Madrid',
            'zip': '28001', 'street': 'Calle Serrano 12',
        })
        wrong_zip = self.env['res.partner'].create({
            'name': 'CP distinto', 'is_restaurant': True, 'city': 'Madrid',
            'zip': '28045', 'street': 'Calle Serrano 99',
        })
        found = search._search_partners()
        self.assertIn(matching, found)
        self.assertNotIn(wrong_zip, found)

    # --- action_toggle_chosen: gate por presupuesto recibido ---

    def test_toggle_chosen_blocked_without_quote(self):
        line = self._create_line(etiqueta='visto')
        with self.assertRaises(UserError):
            line.action_toggle_chosen()

    def test_toggle_chosen_allowed_with_quote_received(self):
        line = self._create_line(etiqueta='presupuesto_recibido', quote_amount=100)
        line.action_toggle_chosen()
        self.assertEqual(self.search.chosen_line_id, line)

    def test_toggle_chosen_can_unset(self):
        line = self._create_line(etiqueta='presupuesto_recibido', quote_amount=100)
        line.action_toggle_chosen()
        line.action_toggle_chosen()
        self.assertFalse(self.search.chosen_line_id)

    # --- action_request_quote ---

    def test_request_quote_requires_email(self):
        line = self._create_line(email=False)
        with self.assertRaises(UserError):
            line.action_request_quote()

    def test_request_quote_sets_etiqueta_and_date(self):
        line = self._create_line(email='chef@example.com')
        line.action_request_quote()
        self.assertEqual(line.etiqueta, 'solicitado')
        self.assertTrue(line.quote_requested_date)

    def test_request_quote_posts_thread_message_with_real_message_id(self):
        """Debe ir por message_post (mail thread), no por un mail.mail suelto --
        si no queda enlazado por Message-Id, una respuesta real nunca podría
        casarse sola con esta línea (ver message_update más abajo)."""
        line = self._create_line(email='chef@example.com')
        line.action_request_quote()
        quote_message = line.message_ids.filtered(lambda m: m.message_type == 'email')
        self.assertEqual(len(quote_message), 1)
        self.assertEqual(quote_message.outgoing_email_to, 'chef@example.com')
        self.assertTrue(quote_message.message_id)

    def test_view_conversation_opens_full_page_not_dialog(self):
        """Odoo nunca muestra el chatter dentro de un diálogo -- por eso esta acción
        tiene que abrir a página completa (target=current), no como el diálogo de
        "Registrar presupuesto" (target=new)."""
        line = self._create_line(email='chef@example.com')
        action = line.action_view_conversation()
        self.assertEqual(action['target'], 'current')
        self.assertEqual(action['res_id'], line.id)

    # --- action_register_quote ---

    def test_register_quote_requires_amount(self):
        line = self._create_line(quote_amount=0)
        with self.assertRaises(UserError):
            line.action_register_quote()

    def test_register_quote_sets_etiqueta(self):
        line = self._create_line(quote_amount=250)
        line.action_register_quote()
        self.assertEqual(line.etiqueta, 'presupuesto_recibido')

    # --- extracción IA del texto pegado (LLM mockeado, sin red real) ---

    def test_extract_quote_from_text_requires_text(self):
        line = self._create_line()
        with self.assertRaises(UserError):
            line.action_extract_quote_from_text()

    def test_extract_quote_from_text_fills_amount(self):
        line = self._create_line(quote_raw_text='Nuestro presupuesto es de 500 euros.')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
            return_value=({'importe': 500, 'notas': 'Sin depósito'}, 'groq'),
        ):
            line.action_extract_quote_from_text()
        self.assertEqual(line.quote_amount, 500)
        self.assertEqual(line.quote_notes, 'Sin depósito')

    def test_extract_quote_from_text_no_amount_found(self):
        line = self._create_line(quote_raw_text='Gracias por el interés, ya os diremos.')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
            return_value=({'importe': None, 'notas': None}, 'groq'),
        ):
            with self.assertRaises(UserError):
                line.action_extract_quote_from_text()

    def test_extract_quote_from_text_llm_unavailable(self):
        line = self._create_line(quote_raw_text='Cualquier texto.')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
            return_value=(None, None),
        ):
            with self.assertRaises(UserError):
                line.action_extract_quote_from_text()

    # --- valoración interna (persiste en el partner, no en la línea) ---

    def test_rating_requires_partner(self):
        line = self._create_line(partner_id=False)
        with self.assertRaises(UserError):
            line.action_rate_liked()

    def test_rating_persists_on_partner(self):
        partner = self.env['res.partner'].create({'name': 'Rest', 'is_restaurant': True})
        line = self._create_line(partner_id=partner.id)
        line.action_rate_liked()
        self.assertEqual(partner.restaurant_internal_rating, 'liked')

    # --- pipeline_stage: progresión completa ---

    def test_pipeline_stage_progression(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self.assertEqual(search.pipeline_stage, 'searching')

        line = self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'google', 'name': 'Rest', 'email': 'a@b.com',
        })
        line.action_request_quote()
        self.assertEqual(search.pipeline_stage, 'quotes_requested')

        line.quote_amount = 100
        line.action_register_quote()
        self.assertEqual(search.pipeline_stage, 'quotes_received')

        line.action_toggle_chosen()
        self.assertEqual(search.pipeline_stage, 'chosen')

    # --- action_view_on_map (mapa propio, Leaflet -- no depende de contacto) ---

    def test_view_on_map_requires_coordinates(self):
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'google', 'name': 'Sin coordenadas',
            'address': 'Calle Falsa 123',
        })
        with self.assertRaises(UserError):
            search.action_view_on_map()

    def test_view_on_map_works_without_partner(self):
        """El punto de tener un mapa propio: no hace falta convertir el resultado
        a contacto para verlo -- basta con que la búsqueda de Google ya trajera
        lat/lng (gratis, en la misma respuesta)."""
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.lead.id, 'city': 'Madrid',
        })
        self.env['restagrup.restaurant.search.line'].create({
            'search_id': search.id, 'source': 'google', 'name': 'Candidato Google',
            'latitude': 40.4168, 'longitude': -3.7038, 'partner_id': False,
        })
        action = search.action_view_on_map()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'restagrup_restaurant_map')
        self.assertEqual(action['params']['search_id'], search.id)

    # --- avisos de peticiones colgadas ---

    def test_quote_is_stale_after_threshold(self):
        line = self._create_line(
            etiqueta='solicitado',
            quote_requested_date=Datetime.now() - timedelta(days=5),
        )
        self.assertTrue(line.quote_is_stale)
        self.assertGreaterEqual(line.quote_days_pending, 3)

    def test_quote_is_not_stale_when_recent(self):
        line = self._create_line(etiqueta='solicitado', quote_requested_date=Datetime.now())
        self.assertFalse(line.quote_is_stale)

    def test_quote_is_not_stale_once_received(self):
        line = self._create_line(
            etiqueta='presupuesto_recibido',
            quote_requested_date=Datetime.now() - timedelta(days=10),
        )
        self.assertFalse(line.quote_is_stale)

    # --- message_update: clasificación IA de la respuesta entrante del restaurante ---
    # (mismo patrón que purchase_order.py::_restagrup_classify_response, portado aquí)

    def test_message_update_extracts_amount_from_incoming_email(self):
        line = self._create_line(etiqueta='solicitado', email='chef@example.com')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
            return_value=({'importe': 480, 'notas': 'Incluye bebida'}, 'groq'),
        ):
            line.message_update({'body': '<p>Nuestro presupuesto: 480 euros, incluye bebida.</p>'})
        self.assertEqual(line.quote_amount, 480)
        self.assertEqual(line.quote_notes, 'Incluye bebida')

    def test_message_update_ignores_reply_when_not_requested(self):
        """Si la línea no está en 'solicitado' (nunca se pidió presupuesto, o ya se
        registró), una respuesta entrante no debe tocar nada -- evita que un email
        fuera de contexto sobrescriba un importe ya confirmado."""
        line = self._create_line(etiqueta='visto', email='chef@example.com')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
        ) as mock_extract:
            line.message_update({'body': '<p>480 euros.</p>'})
            mock_extract.assert_not_called()
        self.assertFalse(line.quote_amount)

    def test_message_update_ignores_empty_body(self):
        line = self._create_line(etiqueta='solicitado', email='chef@example.com')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
        ) as mock_extract:
            line.message_update({'body': ''})
            mock_extract.assert_not_called()

    def test_message_update_llm_unavailable_does_not_raise(self):
        line = self._create_line(etiqueta='solicitado', email='chef@example.com')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
            return_value=(None, None),
        ):
            line.message_update({'body': '<p>480 euros.</p>'})
        self.assertFalse(line.quote_amount)

    # --- recordatorio automático (cron) de peticiones colgadas ---

    def _stale_line(self, **vals):
        defaults = {
            'etiqueta': 'solicitado',
            'email': 'chef@example.com',
            'quote_requested_date': Datetime.now() - timedelta(days=5),
        }
        defaults.update(vals)
        return self._create_line(**defaults)

    def _reminder_messages(self, line):
        return line.message_ids.filtered(lambda m: m.message_type == 'email')

    def test_send_quote_reminder_posts_thread_message_and_stamps_date(self):
        line = self._stale_line()
        line.action_send_quote_reminder()
        messages = self._reminder_messages(line)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages.outgoing_email_to, 'chef@example.com')
        self.assertTrue(messages.message_id)
        self.assertTrue(line.quote_reminder_sent_date)

    def test_send_quote_reminder_uses_configured_text(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'restagrup.quote_reminder_text', 'Texto propio de recordatorio XYZ',
        )
        line = self._stale_line()
        line.action_send_quote_reminder()
        self.assertIn('Texto propio de recordatorio XYZ', self._reminder_messages(line).body)

    def test_send_quote_reminder_default_text_differs_from_request(self):
        line = self._stale_line()
        line.action_send_quote_reminder()
        self.assertIn('recordatorio', self._reminder_messages(line).subject.lower())

    def test_send_quote_reminder_requires_email(self):
        line = self._stale_line(email=False)
        with self.assertRaises(UserError):
            line.action_send_quote_reminder()

    def test_cron_sends_reminder_to_stale_lines_only(self):
        stale = self._stale_line(name='Colgado')
        recent = self._stale_line(name='Reciente', quote_requested_date=Datetime.now())
        received = self._stale_line(name='Recibido', etiqueta='presupuesto_recibido')
        self.env['restagrup.restaurant.search.line']._cron_send_quote_reminders()
        self.assertEqual(len(self._reminder_messages(stale)), 1)
        self.assertFalse(self._reminder_messages(recent))
        self.assertFalse(self._reminder_messages(received))

    def test_cron_does_not_resend_reminder_already_sent(self):
        line = self._stale_line()
        model = self.env['restagrup.restaurant.search.line']
        model._cron_send_quote_reminders()
        model._cron_send_quote_reminders()
        self.assertEqual(len(self._reminder_messages(line)), 1)

    def test_cron_skips_lines_without_email_and_keeps_going(self):
        no_email = self._stale_line(name='Sin email', email=False)
        with_email = self._stale_line(name='Con email')
        self.env['restagrup.restaurant.search.line']._cron_send_quote_reminders()
        self.assertFalse(self._reminder_messages(no_email))
        self.assertEqual(len(self._reminder_messages(with_email)), 1)

    def test_request_quote_again_resets_reminder_date(self):
        line = self._stale_line()
        line.action_send_quote_reminder()
        line.action_request_quote()
        self.assertFalse(line.quote_reminder_sent_date)

    def test_reminder_cron_is_registered_and_daily(self):
        cron = self.env.ref('restagrup_restaurants.ir_cron_send_quote_reminders')
        self.assertEqual(cron.interval_type, 'days')
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.model_id.model, 'restagrup.restaurant.search.line')

    # --- ajustes: la pantalla de Ajustes debe cargar con los campos de Restagrup ---

    def test_settings_screen_loads_and_saves_reminder_text(self):
        """Regresión: un campo Text con config_parameter hacía reventar TODA la pantalla
        de Ajustes ('must have type boolean, integer, float, char...') y ningún test
        lo veía porque nadie abría res.config.settings."""
        settings_model = self.env['res.config.settings']
        settings_model.default_get(list(settings_model._fields))
        settings = settings_model.create({'restagrup_quote_reminder_text': 'Texto de prueba'})
        settings.execute()
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param('restagrup.quote_reminder_text'),
            'Texto de prueba',
        )

    # --- chatter en la búsqueda: aquí se ve todo lo que ocurre con el grupo ---

    def _search_log(self):
        return ' '.join(str(body) for body in self.search.message_ids.mapped('body'))

    def _lead_log(self):
        return ' '.join(str(body) for body in self.lead.message_ids.mapped('body'))

    def test_search_has_its_own_chatter(self):
        self.assertIn('message_ids', self.env['restagrup.restaurant.search']._fields)

    def test_search_form_shows_chatter(self):
        arch = self.env['restagrup.restaurant.search'].get_view(view_type='form')['arch']
        self.assertIn('chatter', arch)

    def test_request_quote_is_logged_on_search_and_still_on_lead(self):
        self._create_line(email='chef@example.com').action_request_quote()
        self.assertIn('Presupuesto solicitado', self._search_log())
        self.assertIn('Presupuesto solicitado', self._lead_log())

    def test_interested_and_discarded_are_logged_on_search(self):
        line = self._create_line(name='Casa Interesante')
        line.action_mark_interesado()
        self.assertIn('Casa Interesante', self._search_log())
        self.assertIn('interesad', self._search_log().lower())
        line.action_mark_descartado()
        self.assertIn('descartad', self._search_log().lower())

    def test_choose_and_unchoose_are_logged_on_search(self):
        line = self._create_line(name='Casa Elegida', etiqueta='presupuesto_recibido', quote_amount=100)
        with patch.object(self.env.registry['restagrup.restaurant.search.line'], '_fetch_google_phone'):
            line.action_toggle_chosen()
            self.assertIn('Elegido', self._search_log())
            self.assertIn('Casa Elegida', self._search_log())
            line.action_toggle_chosen()
        self.assertIn('Ya no es el elegido', self._search_log())

    def test_restaurant_reply_is_logged_on_search_with_excerpt(self):
        line = self._create_line(name='Casa Que Responde', etiqueta='solicitado', email='chef@example.com')
        with patch(
            'odoo.addons.restagrup_core.models.llm_connector.RestagrupLlmConnector.extract_json',
            return_value=({'importe': 500, 'notas': 'Sin depósito'}, 'groq'),
        ):
            line.message_update({'body': '<p>Les podemos ofrecer el menú por 500 euros para el grupo.</p>'})
        log = self._search_log()
        self.assertIn('Casa Que Responde', log)
        self.assertIn('500 euros', log)

    def test_reminder_is_logged_on_search(self):
        line = self._stale_line(name='Casa Sin Respuesta')
        line.action_send_quote_reminder()
        log = self._search_log()
        self.assertIn('Recordatorio enviado', log)
        self.assertIn('Casa Sin Respuesta', log)
