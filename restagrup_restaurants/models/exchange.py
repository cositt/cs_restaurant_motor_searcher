# -*- coding: utf-8 -*-
"""Cambio de moneda de los restaurantes de fuera de la zona euro. Como el CRM de Restagrup, los tipos son los del
Banco Central Europeo a través de api.frankfurter.dev. Se guardan como tipos de cambio de Odoo (res.currency.rate),
así quedan a la vista y con su fecha."""
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

FRANKFURTER_URL = 'https://api.frankfurter.dev/v1/latest'
TIMEOUT_SECONDS = 10
# Las monedas con las que trabaja Restagrup (las mismas de su CRM).
CURRENCY_CODES = ('EUR', 'USD', 'GBP', 'CHF', 'NOK', 'SEK', 'DKK', 'CZK', 'PLN', 'HUF', 'RON', 'BGN', 'RSD',
                  'TRY', 'MAD')
CURRENCY_SELECTION = [(code, code) for code in CURRENCY_CODES]


class RestagrupExchange(models.AbstractModel):
    _name = 'restagrup.exchange'
    _description = 'Cambio de moneda (BCE)'

    @api.model
    def currency_by_code(self, code):
        """La moneda de Odoo con ese código, aunque esté archivada: no hace falta activar la multimoneda."""
        currency = self.env['res.currency'].with_context(active_test=False).search([('name', '=', code)], limit=1)
        return currency or self.env.company.currency_id

    @api.model
    def _fetch_rates(self, codes):
        """{código: unidades por 1 €} del BCE. Error claro si el servicio no responde."""
        try:
            response = requests.get(
                FRANKFURTER_URL, params={'base': 'EUR', 'symbols': ','.join(codes)}, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json().get('rates') or {}
        except (requests.RequestException, ValueError) as error:
            _logger.warning('Cambio del BCE no disponible (%s): %s', ','.join(codes), error)
            raise UserError(_('No se ha podido consultar el cambio del Banco Central Europeo. Inténtalo en un rato.'))

    @api.model
    def refresh_rates(self, currencies):
        """Trae el cambio de hoy de esas monedas y lo guarda. Devuelve {código: unidades por 1 €}."""
        company = self.env.company
        foreign = currencies.filtered(lambda c: c != company.currency_id)
        if not foreign:
            return {}
        rates = self._fetch_rates(sorted(set(foreign.mapped('name'))))
        today = fields.Date.context_today(self)
        Rate = self.env['res.currency.rate'].sudo()
        for currency in foreign:
            value = rates.get(currency.name)
            if not value:
                continue
            existing = Rate.search([
                ('currency_id', '=', currency.id), ('company_id', '=', company.id), ('name', '=', today)], limit=1)
            if existing:
                existing.rate = value
            else:
                Rate.create({'currency_id': currency.id, 'company_id': company.id, 'name': today, 'rate': value})
        return rates

    @api.model
    def eur_per_unit(self, currency, date=None):
        """Euros que vale 1 unidad de la moneda con el último cambio guardado; 0 si aún no hay ninguno (nunca
        se supone 1:1, que daría precios falsos)."""
        company = self.env.company
        if not currency or currency == company.currency_id:
            return 1.0
        rate = self.env['res.currency.rate'].sudo().search([
            ('currency_id', '=', currency.id), ('company_id', 'in', (company.id, False)),
            ('name', '<=', date or fields.Date.context_today(self))], order='name desc', limit=1)
        return 1.0 / rate.rate if rate.rate else 0.0

    @api.model
    def _currencies_in_use(self):
        codes = set(self.env['res.partner'].search([
            ('is_restaurant', '=', True), ('restaurant_currency_code', 'not in', (False, 'EUR'))],
        ).mapped('restaurant_currency_code'))
        codes |= set(self.env['restagrup.restaurant.menu'].search([]).mapped('currency_id.name'))
        currencies = self.env['res.currency'].with_context(active_test=False).search([('name', 'in', list(codes))])
        return currencies - self.env.company.currency_id

    @api.model
    def _cron_refresh_rates(self):
        """Cron diario: el cambio de hoy de las monedas que usan los restaurantes, para el aviso de variación."""
        currencies = self._currencies_in_use()
        if not currencies:
            return
        try:
            self.refresh_rates(currencies)
        except UserError:
            _logger.warning('Cron de cambio de moneda: el BCE no respondió; se reintenta mañana.')
