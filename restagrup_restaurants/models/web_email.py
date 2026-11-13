# -*- coding: utf-8 -*-
"""Email de un restaurante de Google sacado de su web (ronda de ajustes 11/11, lo hablado con Gerard).

Google Places no da email, pero sí la web del restaurante (Place Details, una llamada de pago: solo bajo demanda, al
pedirle presupuesto). Se lee la portada y, si ahí no está, su página de contacto. Se prefiere el email del propio
dominio del restaurante y se descartan nombres de imagen y direcciones técnicas."""
import logging
import re
from urllib.parse import urljoin, urlparse

import requests

from odoo import _, models

from .restaurant_search import GOOGLE_PLACES_DETAILS_URL

_logger = logging.getLogger(__name__)

TIMEOUT = 8
MAX_HTML_CHARS = 1_500_000
MAX_CONTACT_PAGES = 2
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; RestagrupBot/1.0)'}
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
CONTACT_HREF_RE = re.compile(r'href=["\']([^"\'#]*(?:contact|contacto|reserva)[^"\'#]*)["\']', re.IGNORECASE)
IGNORED_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.css', '.js')
IGNORED_DOMAINS = ('sentry', 'wixpress', 'example.com', 'domain.com', 'email.com', 'godaddy', 'cloudflare')


def _host(url):
    host = (urlparse(url).hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def pick_email(html, site_host):
    """El mejor email de una página: primero el del dominio del restaurante, si no, el primero válido."""
    candidates = []
    for email in EMAIL_RE.findall(html or ''):
        lowered = email.lower().strip('.')
        domain = lowered.rsplit('@', 1)[-1]
        if lowered.endswith(IGNORED_SUFFIXES) or any(bad in domain for bad in IGNORED_DOMAINS):
            continue
        if lowered not in candidates:
            candidates.append(lowered)
    own = [email for email in candidates if site_host and email.endswith('@' + site_host)]
    return (own or candidates or [False])[0]


class RestaurantSearchLineWebEmail(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def _restagrup_google_website(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('restagrup.google_places_api_key')
        if not (api_key and self.google_place_id):
            return ''
        try:
            response = requests.get(GOOGLE_PLACES_DETAILS_URL, params={
                'place_id': self.google_place_id, 'fields': 'website', 'key': api_key}, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            _logger.warning('No se pudo pedir la web de %s a Google Places', self.name)
            return ''
        return ((payload.get('result') or {}).get('website') or '') if payload.get('status') == 'OK' else ''

    @staticmethod
    def _restagrup_get_page(url):
        if urlparse(url).scheme not in ('http', 'https'):
            return ''
        try:
            response = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
            response.raise_for_status()
        except requests.RequestException:
            _logger.info('No se pudo leer %s buscando el email del restaurante', url)
            return ''
        return (response.text or '')[:MAX_HTML_CHARS]

    def _restagrup_find_web_email(self):
        """Busca el email en la web del restaurante y lo guarda en el resultado. Devuelve el email o False."""
        self.ensure_one()
        if self.email:
            return self.email
        if self.source != 'google':
            return False
        website = self._restagrup_google_website()
        if not website:
            return False
        site_host = _host(website)
        home = self._restagrup_get_page(website)
        email = pick_email(home, site_host)
        if not email:
            links = []
            for href in CONTACT_HREF_RE.findall(home):
                url = urljoin(website, href)
                if _host(url) == site_host and url not in links:
                    links.append(url)
            for url in links[:MAX_CONTACT_PAGES]:
                email = pick_email(self._restagrup_get_page(url), site_host)
                if email:
                    break
        if email:
            self.email = email
            self.search_id.message_post_if_exists(
                _('%(name)s: email sacado de su web (%(web)s): %(email)s.', name=self.name, web=website, email=email))
        return email

    def action_add_as_partner(self):
        """Reunión 12/11 (8.1): al añadirlo como contacto también se busca el email en su web."""
        for line in self.filtered(lambda l: not l.partner_id and not l.email):
            line._restagrup_find_web_email()
        return super().action_add_as_partner()

    def _get_quote_email_to(self):
        if not (self.partner_id.email or self.email or self._quote_contact_email()):
            self._restagrup_find_web_email()
        return super()._get_quote_email_to()
