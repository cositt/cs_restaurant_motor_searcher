# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

PARAM = 'restagrup.default_margin_percent'


@tagged('post_install', '-at_install')
class TestPricing(TransactionCase):
    """Regla de negocio: Restagrup vende al cliente el precio del restaurante + 20 %."""

    def _pricing(self):
        return self.env['restagrup.pricing']

    def _set_margin(self, value):
        self.env['ir.config_parameter'].sudo().set_param(PARAM, value)

    def test_margin_is_20_percent_when_not_configured(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', PARAM)]).unlink()
        self.assertEqual(self._pricing().margin_percent(), 20.0)
        self.assertAlmostEqual(self._pricing().apply_margin(100.0), 120.0)

    def test_explicit_zero_is_respected(self):
        self._set_margin('0')
        self.assertEqual(self._pricing().margin_percent(), 0.0)
        self.assertAlmostEqual(self._pricing().apply_margin(100.0), 100.0)

    def test_custom_margin_is_applied(self):
        self._set_margin('15')
        self.assertAlmostEqual(self._pricing().apply_margin(200.0), 230.0)

    def test_invalid_value_falls_back_to_the_default_not_to_zero(self):
        self._set_margin('no-es-un-numero')
        self.assertEqual(self._pricing().margin_percent(), 20.0)

    def test_zero_cost_stays_zero(self):
        self.assertEqual(self._pricing().apply_margin(0.0), 0.0)

    # --- el 20 % lo puede cambiar Restagrup desde Ajustes -> Restagrup ---

    def test_settings_screen_shows_20_when_nothing_is_saved(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', PARAM)]).unlink()
        defaults = self.env['res.config.settings'].default_get(['restagrup_default_margin_percent'])
        self.assertEqual(defaults['restagrup_default_margin_percent'], 20.0)

    def test_company_can_change_the_margin_from_settings(self):
        settings = self.env['res.config.settings'].create({'restagrup_default_margin_percent': 25.0})
        settings.execute()
        self.assertEqual(self._pricing().margin_percent(), 25.0)
        self.assertAlmostEqual(self._pricing().apply_margin(100.0), 125.0)

    def test_company_can_set_the_margin_to_zero_from_settings(self):
        settings = self.env['res.config.settings'].create({'restagrup_default_margin_percent': 0.0})
        settings.execute()
        self.assertEqual(self._pricing().margin_percent(), 0.0)
