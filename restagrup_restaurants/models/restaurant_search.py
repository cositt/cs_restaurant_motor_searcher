# -*- coding: utf-8 -*-
import logging
import time
from datetime import timedelta
from urllib.parse import quote

import requests
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

GOOGLE_PLACES_TEXTSEARCH_URL = 'https://maps.googleapis.com/maps/api/place/textsearch/json'
GOOGLE_PLACES_NEARBYSEARCH_URL = 'https://maps.googleapis.com/maps/api/place/nearbysearch/json'
GOOGLE_PLACES_DETAILS_URL = 'https://maps.googleapis.com/maps/api/place/details/json'
GOOGLE_GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'
# Radio de Nearby Search alrededor del punto geocodificado (calle + CP + ciudad) --
# pensado para acotar a un barrio/código postal concreto, no a la ciudad entera.
GOOGLE_PLACES_SEARCH_RADIUS_METERS = 3000
# Tope propio: hasta 2 páginas (40 resultados) por búsqueda. Google permite hasta 3
# (60, su tope duro), pero cada página extra es una llamada facturable más y obliga a
# esperar ~2s a que el next_page_token esté listo -- 2 páginas es el punto medio que se
# decidió entre resultados y coste/tiempo de espera.
GOOGLE_PLACES_MAX_PAGES = 2
GOOGLE_PLACES_NEXT_PAGE_DELAY = 2
# Google no da un tiempo fijo de activación del next_page_token -- 2s a veces no basta
# y devuelve INVALID_REQUEST. Se reintenta esperando cada vez un poco más (2s, 3s, 4s,
# 5s) antes de rendirse -- hasta ~14s extra en el peor caso.
GOOGLE_PLACES_NEXT_PAGE_MAX_RETRIES = 4

PRICE_LEVEL_SELECTION = [('1', '€'), ('2', '€€'), ('3', '€€€'), ('4', '€€€€')]

EXTRACT_QUOTE_SYSTEM_PROMPT = """\
Eres un asistente que lee la respuesta de un restaurante a una petición de presupuesto
para un grupo. Devuelve SOLO un objeto JSON, sin texto adicional, con estas claves
exactas: "importe" (número en euros -- el precio total indicado, o null si no aparece
un importe claro), "notas" (string corto con condiciones relevantes mencionadas --
fecha alternativa, aforo distinto, política de cancelación, depósito -- o null si no
hay nada relevante).
Si un dato no aparece claramente en el texto, pon null -- nunca lo inventes."""

ETIQUETA_SELECTION = [
    ('visto', 'Visto'),
    ('interesado', 'Interesado'),
    ('solicitado', 'Solicitado'),
    ('presupuesto_recibido', 'Presupuesto recibido'),
    ('descartado', 'Descartado'),
]

PIPELINE_STAGE_SELECTION = [
    ('searching', 'Buscando'),
    ('quotes_requested', 'Presupuestos pedidos'),
    ('quotes_received', 'Presupuestos recibidos'),
    ('chosen', 'Elegido'),
]

# Antigüedad a partir de la cual una petición de presupuesto "solicitado" se marca
# como colgada en el kanban -- aviso visual, no bloquea nada.
QUOTE_STALE_DAYS = 3
QUOTE_REMINDER_DEFAULT_TEXT = (
    'Hola,\n\nOs escribimos de %(company)s: hace unos días os pedimos presupuesto para un'
    ' evento y todavía no hemos recibido respuesta. ¿Podríais enviárnoslo o decirnos si no'
    ' os es posible?\n\nGracias.'
)

SORT_BY_SELECTION = [
    ('default', 'Por defecto'),
    ('rating_desc', 'Mejor valorados'),
    ('price_asc', 'Precio: más barato primero'),
    ('price_desc', 'Precio: más caro primero'),
    ('capacity_desc', 'Mayor aforo'),
    ('name_asc', 'Nombre (A-Z)'),
]

# Campo booleano del wizard -> (tipo de Google Places, texto para el query de fallback).
# Google no deja pedir varios "type" en una sola llamada -- cada tipo marcado dispara su
# propia búsqueda (Nearby Search o, si falló el geocoding, Text Search), y luego se
# deduplica por place_id porque un mismo sitio puede tener varios tipos a la vez en
# Google (p.ej. un bar de tapas suele venir marcado como 'bar', no 'restaurant').
GOOGLE_PLACE_TYPE_FIELDS = [
    ('search_type_restaurant', 'restaurant', 'restaurantes'),
    ('search_type_bar', 'bar', 'bares'),
    ('search_type_cafe', 'cafe', 'cafeterías'),
    ('search_type_fastfood', 'meal_takeaway', 'comida rápida'),
]


class RestaurantSearch(models.Model):
    _name = 'restagrup.restaurant.search'
    _description = 'Búsqueda de restaurantes para un grupo'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    lead_id = fields.Many2one(
        'crm.lead', string='Grupo / Cliente', required=True, ondelete='cascade', index=True,
        help='La oportunidad o petición de grupo para la que se buscan restaurantes.',
    )
    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)
    city = fields.Char(string='Ciudad', required=True)
    street = fields.Char(string='Calle', help='Opcional -- afina la geolocalización de Google.')
    zip = fields.Char(
        string='Código postal',
        help='Opcional -- afina tanto la geolocalización de Google como el match con'
             ' restaurantes ya guardados en Odoo.',
    )
    min_capacity = fields.Integer(string='Aforo mínimo')
    require_bus_parking = fields.Boolean(string='Con parking de autobús')
    cuisine_type = fields.Char(string='Tipo de cocina')
    max_price_level = fields.Selection(selection=PRICE_LEVEL_SELECTION, string='Precio máximo')
    search_type_restaurant = fields.Boolean(string='Restaurantes', default=True)
    search_type_bar = fields.Boolean(
        string='Bares / tascas', default=True,
        help='Google clasifica muchas tascas y bares de tapas como "bar", no como'
             ' "restaurant" -- sin esto se quedan fuera aunque sean válidos para el grupo.',
    )
    search_type_cafe = fields.Boolean(string='Cafeterías', default=False)
    search_type_fastfood = fields.Boolean(string='Comida rápida', default=False)
    notes = fields.Text(string='Notas de la búsqueda')
    user_id = fields.Many2one('res.users', string='Buscado por', default=lambda self: self.env.user)
    chosen_line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Restaurante elegido',
        domain="[('search_id', '=', id)]", copy=False,
    )
    line_ids = fields.One2many('restagrup.restaurant.search.line', 'search_id', string='Resultados')
    line_count = fields.Integer(string='Nº resultados', compute='_compute_line_count')
    sort_by = fields.Selection(
        selection=SORT_BY_SELECTION, string='Ordenar por', default='default',
        help='Reordena las tarjetas de resultados. No afecta a los datos, solo al orden en que se muestran.',
    )
    active = fields.Boolean(default=True)
    pipeline_stage = fields.Selection(
        selection=PIPELINE_STAGE_SELECTION, string='Estado', compute='_compute_pipeline_stage',
        store=True, default='searching',
        help='Se calcula solo a partir de las etiquetas de los resultados y del'
             ' restaurante elegido -- no es editable a mano.',
    )

    @api.depends('city', 'zip', 'min_capacity')
    def _compute_display_name(self):
        for search in self:
            location = search.city or _('Sin ciudad')
            if search.zip:
                location = f'{location} {search.zip}'
            parts = [location]
            if search.min_capacity:
                parts.append(_('%s pax') % search.min_capacity)
            search.display_name = ' · '.join(parts)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for search in self:
            search.line_count = len(search.line_ids)

    @api.depends('chosen_line_id', 'line_ids.etiqueta')
    def _compute_pipeline_stage(self):
        for search in self:
            etiquetas = search.line_ids.mapped('etiqueta')
            if search.chosen_line_id:
                search.pipeline_stage = 'chosen'
            elif 'presupuesto_recibido' in etiquetas:
                search.pipeline_stage = 'quotes_received'
            elif 'solicitado' in etiquetas:
                search.pipeline_stage = 'quotes_requested'
            else:
                search.pipeline_stage = 'searching'

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        if self.lead_id and not self.city:
            self.city = self.lead_id.restagrup_city
        if self.lead_id and not self.min_capacity:
            self.min_capacity = self.lead_id.restagrup_pax

    def _sort_key_for(self, sort_by):
        if sort_by == 'default':
            return (lambda line: line.default_sequence), False
        if sort_by == 'rating_desc':
            return (lambda line: line.rating or 0), True
        if sort_by == 'price_asc':
            # (sin precio conocido, precio) -- así lo desconocido siempre va al final.
            return (lambda line: (not line.price_level, int(line.price_level or 0))), False
        if sort_by == 'price_desc':
            return (lambda line: (not line.price_level, -int(line.price_level or 0))), False
        if sort_by == 'capacity_desc':
            return (lambda line: line.capacity or 0), True
        if sort_by == 'name_asc':
            return (lambda line: (line.name or '').lower()), False
        return None, False

    def action_apply_sort(self):
        """Reordena de verdad en base de datos (no vale hacerlo solo en un onchange:
        Odoo descarta esos cambios de las líneas al terminar el onchange). Sin devolver
        una acción, el cliente web recarga solo el registro actual -- el kanban vuelve a
        pedir los datos ya en el nuevo orden (_order = 'sequence, id' del modelo de
        línea) sin apilar una entrada nueva en el breadcrumb."""
        self.ensure_one()
        key, reverse = self._sort_key_for(self.sort_by)
        if key and self.line_ids:
            for index, line in enumerate(sorted(self.line_ids, key=key, reverse=reverse)):
                line.sequence = (index + 1) * 10

    def action_search(self):
        self.ensure_one()
        existing_partner_ids = set(self.line_ids.filtered(lambda l: l.source == 'partner').mapped('partner_id.id'))
        existing_place_ids = set(self.line_ids.mapped('google_place_id')) - {False}
        next_sequence = (max(self.line_ids.mapped('sequence')) + 10) if self.line_ids else 10

        new_lines = []
        for partner in self._search_partners():
            if partner.id in existing_partner_ids:
                continue
            new_lines.append(self._partner_to_line_vals(partner, next_sequence))
            next_sequence += 10

        for candidate in self._search_google(existing_place_ids):
            new_lines.append(dict(candidate, sequence=next_sequence, default_sequence=next_sequence))
            next_sequence += 10

        if new_lines:
            self.env['restagrup.restaurant.search.line'].create(new_lines)
        else:
            self.message_post_if_exists(_('Buscar restaurantes: sin resultados nuevos.'))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_on_map(self):
        """Mapa propio (Leaflet + OpenStreetMap, sin coste) con TODOS los resultados
        que tengan coordenadas -- a diferencia de la vista <map> nativa de Odoo, no
        depende de que el resultado esté guardado como contacto (Google Places ya
        da lat/lng en la propia respuesta de búsqueda, gratis)."""
        self.ensure_one()
        if not self.line_ids.filtered(lambda l: l.latitude and l.longitude):
            raise UserError(_(
                'Ningún resultado tiene coordenadas todavía. Los candidatos de'
                ' Google las traen solos al buscar; los que vinieran de un'
                ' contacto guardado sin geocodificar, no.'
            ))
        return {
            'type': 'ir.actions.client',
            'tag': 'restagrup_restaurant_map',
            'name': _('%s — en el mapa') % self.display_name,
            'target': 'current',
            'params': {'search_id': self.id},
        }

    def message_post_if_exists(self, body):
        # crm.lead lleva chatter; dejamos constancia ahí de que se repitió una búsqueda sin resultados nuevos.
        if self.lead_id:
            self.lead_id.message_post(body=body)

    def _full_address_text(self):
        """Dirección completa a partir de los campos independientes -- vacía si no
        se rellenó ninguno."""
        return ', '.join(part for part in (self.street, self.zip, self.city) if part)

    def _search_partners(self):
        domain = [('is_restaurant', '=', True)]
        if self.city:
            domain.append(('city', 'ilike', self.city))
        if self.zip:
            domain.append(('zip', 'ilike', self.zip))
        if self.street:
            domain.append(('street', 'ilike', self.street))
        if self.min_capacity:
            domain.append(('restaurant_capacity', '>=', self.min_capacity))
        if self.require_bus_parking:
            domain.append(('restaurant_bus_parking', '=', True))
        if self.cuisine_type:
            domain.append(('restaurant_cuisine_type', 'ilike', self.cuisine_type))
        if self.max_price_level:
            domain.append(('restaurant_price_level', '<=', self.max_price_level))
        return self.env['res.partner'].search(domain, order='name')

    def _partner_to_line_vals(self, partner, sequence):
        return {
            'search_id': self.id,
            'sequence': sequence,
            'default_sequence': sequence,
            'source': 'partner',
            'name': partner.name,
            'address': partner.street or '',
            'phone': partner.phone or '',
            'email': partner.email or '',
            'rating': partner.restaurant_google_rating,
            'review_count': partner.restaurant_google_review_count,
            'google_place_id': partner.restaurant_google_place_id,
            'partner_id': partner.id,
            'cuisine_type': partner.restaurant_cuisine_type,
            'price_level': partner.restaurant_price_level,
            'capacity': partner.restaurant_capacity,
            'bus_parking': partner.restaurant_bus_parking,
            'suitable_corporate': partner.restaurant_suitable_corporate,
            'suitable_school': partner.restaurant_suitable_school,
            'suitable_family': partner.restaurant_suitable_family,
            'internal_notes': partner.restaurant_internal_notes,
            'latitude': partner.partner_latitude,
            'longitude': partner.partner_longitude,
        }

    def _fetch_google_places_page(self, url, params, page_num):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            _logger.exception('Fallo llamando a Google Places (página %s)', page_num)
            return None

    def _fetch_google_places_pages(self, search_url, params, api_key):
        """Pagina hasta GOOGLE_PLACES_MAX_PAGES sobre una búsqueda (Nearby o Text
        Search) ya armada, con reintentos en el next_page_token. Devuelve la lista
        cruda de 'results' de todas las páginas obtenidas."""
        raw_results = []
        page_params = params
        for page in range(GOOGLE_PLACES_MAX_PAGES):
            if page == 0:
                payload = self._fetch_google_places_page(search_url, page_params, page + 1)
            else:
                payload = None
                for attempt in range(GOOGLE_PLACES_NEXT_PAGE_MAX_RETRIES):
                    # Espera creciente (2s, 3s, 4s...): 2s fijos no bastan siempre --
                    # el next_page_token de Google no tiene un tiempo de activación fijo.
                    time.sleep(GOOGLE_PLACES_NEXT_PAGE_DELAY + attempt)
                    payload = self._fetch_google_places_page(search_url, page_params, page + 1)
                    if payload and payload.get('status') != 'INVALID_REQUEST':
                        break

            if not payload or payload.get('status') not in ('OK', 'ZERO_RESULTS'):
                if payload:
                    _logger.warning('Google Places devolvió status=%s (página %s)', payload.get('status'), page + 1)
                break

            raw_results += payload.get('results', [])
            next_page_token = payload.get('next_page_token')
            if not next_page_token:
                break
            page_params = {'pagetoken': next_page_token, 'key': api_key}
        return raw_results

    def _geocode_address(self, api_key):
        """Convierte la dirección completa (calle + CP + ciudad, los que estén
        rellenos) en lat/lng para poder buscar por radio real con Nearby Search --
        un Text Search de texto libre no respeta un código postal como filtro
        geográfico, solo lo trata como palabras más a buscar. Cuantos más campos
        estén rellenos, más preciso el punto geocodificado."""
        address = self._full_address_text()
        if not address:
            return None
        try:
            response = requests.get(
                GOOGLE_GEOCODE_URL, params={'address': address, 'key': api_key}, timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            _logger.exception('Fallo geocodificando "%s"', address)
            return None
        if payload.get('status') != 'OK' or not payload.get('results'):
            _logger.warning('Geocoding sin resultados para "%s" (status=%s)', address, payload.get('status'))
            return None
        location = payload['results'][0]['geometry']['location']
        return location['lat'], location['lng']

    def _build_google_search_params(self, api_key, coords, google_type, type_label):
        if coords:
            lat, lng = coords
            search_url = GOOGLE_PLACES_NEARBYSEARCH_URL
            params = {
                'location': f'{lat},{lng}',
                'radius': GOOGLE_PLACES_SEARCH_RADIUS_METERS,
                'type': google_type,
                'key': api_key,
            }
            if self.cuisine_type:
                params['keyword'] = self.cuisine_type
        else:
            # Sin coordenadas (geocoding falló o no hay ciudad): se cae al texto libre
            # de antes, que al menos no deja al usuario sin resultados.
            search_url = GOOGLE_PLACES_TEXTSEARCH_URL
            query = f'{type_label} {self.cuisine_type or ""} para grupos en {self._full_address_text()}'.replace('  ', ' ').strip()
            params = {'query': query, 'key': api_key}
        if self.max_price_level:
            # Nuestra escala (1=€ .. 4=€€€€) coincide 1:1 con el price_level de Google
            # (1=Inexpensive .. 4=Very Expensive) -- sin desplazamiento.
            params['maxprice'] = int(self.max_price_level)
        return search_url, params

    def _search_google(self, known_place_ids):
        api_key = self.env['ir.config_parameter'].sudo().get_param('restagrup.google_places_api_key')
        if not api_key:
            _logger.info('Google Places sin configurar (Ajustes > Restagrup) — solo se muestran partners.')
            return []

        known_place_ids = set(known_place_ids) | set(
            self.env['res.partner'].search([('restaurant_google_place_id', '!=', False)])
            .mapped('restaurant_google_place_id')
        )

        selected_types = [
            (google_type, type_label)
            for field_name, google_type, type_label in GOOGLE_PLACE_TYPE_FIELDS
            if getattr(self, field_name)
        ] or [('restaurant', 'restaurantes')]  # salvaguarda si se desmarcan los 4

        coords = self._geocode_address(api_key)

        # Un mismo local puede tener varios tipos en Google a la vez (un bar de tapas
        # puede salir tanto en la búsqueda 'bar' como en 'restaurant'), así que se
        # deduplica por place_id entre las distintas búsquedas por tipo.
        raw_results = []
        seen_place_ids = set()
        for google_type, type_label in selected_types:
            search_url, params = self._build_google_search_params(api_key, coords, google_type, type_label)
            for place in self._fetch_google_places_pages(search_url, params, api_key):
                place_id = place.get('place_id')
                if place_id and place_id in seen_place_ids:
                    continue
                if place_id:
                    seen_place_ids.add(place_id)
                raw_results.append(place)

        candidates = [
            place for place in raw_results
            if place.get('place_id') not in known_place_ids
        ]
        candidates.sort(
            key=lambda p: (p.get('rating') or 0, p.get('user_ratings_total') or 0),
            reverse=True,
        )

        lines = []
        for place in candidates:
            google_price = place.get('price_level')
            location = place.get('geometry', {}).get('location', {})
            lines.append({
                'search_id': self.id,
                'source': 'google',
                'name': place.get('name', ''),
                # Nearby Search devuelve 'vicinity' (dirección corta); Text Search
                # (el fallback) devuelve 'formatted_address'.
                'address': place.get('vicinity') or place.get('formatted_address', ''),
                'rating': place.get('rating') or 0,
                'review_count': place.get('user_ratings_total') or 0,
                'google_place_id': place.get('place_id'),
                # 1:1 con la escala de Google -- su nivel 0 ("Free") no tiene
                # equivalente en la nuestra (empieza en 1=€), se deja sin precio.
                'price_level': str(google_price) if google_price and 1 <= google_price <= 4 else False,
                # Ya viene en la misma respuesta de Places -- gratis, sin llamada
                # extra. Permite pintar el mapa propio sin depender de que el
                # resultado se haya guardado como contacto.
                'latitude': location.get('lat'),
                'longitude': location.get('lng'),
            })
        return lines


class RestaurantSearchLine(models.Model):
    _name = 'restagrup.restaurant.search.line'
    _inherit = ['mail.thread']
    _description = 'Resultado del buscador de restaurantes'
    _order = 'sequence, id'

    search_id = fields.Many2one('restagrup.restaurant.search', required=True, ondelete='cascade', index=True)
    lead_id = fields.Many2one(related='search_id.lead_id', store=True, string='Grupo / Cliente')
    sequence = fields.Integer(default=10)
    default_sequence = fields.Integer(
        default=10,
        help='Copia del orden en que se encontró el resultado, para poder volver a "Por defecto"'
             ' después de reordenar por otro criterio.',
    )
    source = fields.Selection([('partner', 'Ya en Odoo'), ('google', 'Google Places')], required=True)
    name = fields.Char(string='Nombre')
    address = fields.Char(string='Dirección')
    phone = fields.Char(string='Teléfono')
    email = fields.Char(string='Email')
    rating = fields.Float(string='Rating')
    review_count = fields.Integer(string='Nº reseñas')
    google_place_id = fields.Char(string='Google Place ID')
    partner_id = fields.Many2one('res.partner', string='Contacto')

    cuisine_type = fields.Char(string='Tipo de cocina')
    price_level = fields.Selection(selection=PRICE_LEVEL_SELECTION, string='Nivel de precio')
    price_label = fields.Char(string='Precio', compute='_compute_price_label')
    capacity = fields.Integer(string='Aforo (grupos)')
    bus_parking = fields.Boolean(string='Parking de autobús')
    suitable_corporate = fields.Boolean(string='Apto corporativo')
    suitable_school = fields.Boolean(string='Apto escolar')
    suitable_family = fields.Boolean(string='Apto familiar')
    internal_notes = fields.Text(string='Notas internas')

    etiqueta = fields.Selection(selection=ETIQUETA_SELECTION, string='Etiqueta', default='visto', required=True)
    partner_restaurant_rating = fields.Selection(
        related='partner_id.restaurant_internal_rating', string='Valoración interna',
    )
    quote_amount = fields.Float(string='Presupuesto (€)', digits=(16, 2))
    quote_notes = fields.Text(string='Notas del presupuesto')
    quote_raw_text = fields.Text(
        string='Texto de la respuesta del restaurante',
        help='Pega aquí el email/mensaje del restaurante para que la IA proponga el'
             ' importe -- siempre a revisar antes de registrar, nunca se registra sola.',
    )
    quote_requested_date = fields.Datetime(string='Fecha de solicitud', copy=False)
    quote_reminder_sent_date = fields.Datetime(
        string='Recordatorio enviado', copy=False,
        help='Fecha del recordatorio automático. Solo se manda uno por petición: se'
             ' vacía al volver a pedir presupuesto.',
    )
    quote_days_pending = fields.Integer(
        string='Días esperando presupuesto', compute='_compute_quote_days_pending',
    )
    quote_is_stale = fields.Boolean(
        string='Petición colgada', compute='_compute_quote_days_pending',
        help='Lleva más de %s días en "Solicitado" sin presupuesto recibido ni descartado.' % QUOTE_STALE_DAYS,
    )
    is_chosen = fields.Boolean(string='Elegido', compute='_compute_is_chosen')
    google_maps_url = fields.Char(string='Enlace Maps', compute='_compute_google_maps_url')
    latitude = fields.Float(string='Latitud', digits=(16, 6))
    longitude = fields.Float(string='Longitud', digits=(16, 6))

    @api.depends('price_level')
    def _compute_price_label(self):
        labels = dict(PRICE_LEVEL_SELECTION)
        for line in self:
            line.price_label = labels.get(line.price_level, '')

    @api.depends('search_id.chosen_line_id')
    def _compute_is_chosen(self):
        for line in self:
            line.is_chosen = line.search_id.chosen_line_id.id == line.id

    @api.depends('etiqueta', 'quote_requested_date')
    def _compute_quote_days_pending(self):
        now = fields.Datetime.now()
        for line in self:
            if line.etiqueta == 'solicitado' and line.quote_requested_date:
                days = (now - line.quote_requested_date).days
            else:
                days = 0
            line.quote_days_pending = days
            line.quote_is_stale = line.etiqueta == 'solicitado' and days >= QUOTE_STALE_DAYS

    @api.depends('google_place_id', 'address', 'name')
    def _compute_google_maps_url(self):
        for line in self:
            if line.google_place_id:
                line.google_maps_url = f'https://www.google.com/maps/place/?q=place_id:{line.google_place_id}'
            elif line.address:
                line.google_maps_url = f'https://www.google.com/maps/search/?api=1&query={quote(line.address)}'
            else:
                line.google_maps_url = False

    def _fetch_google_phone(self):
        """Google Places Text Search (la búsqueda inicial) no devuelve teléfono -- solo
        lo da el endpoint Place Details, que es una llamada aparte y facturable por
        restaurante. Por coste, solo se pide aquí, bajo demanda, para el restaurante
        concreto que el usuario elige o añade como contacto -- nunca para los 20
        resultados de golpe."""
        self.ensure_one()
        if self.source != 'google' or not self.google_place_id or self.phone:
            return
        api_key = self.env['ir.config_parameter'].sudo().get_param('restagrup.google_places_api_key')
        if not api_key:
            return
        params = {
            'place_id': self.google_place_id,
            'fields': 'formatted_phone_number,international_phone_number',
            'key': api_key,
        }
        try:
            response = requests.get(GOOGLE_PLACES_DETAILS_URL, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            _logger.exception('Fallo pidiendo teléfono a Google Places Details (place_id=%s)', self.google_place_id)
            return
        if payload.get('status') != 'OK':
            _logger.warning('Google Places Details devolvió status=%s para place_id=%s', payload.get('status'), self.google_place_id)
            return
        result = payload.get('result') or {}
        phone = result.get('formatted_phone_number') or result.get('international_phone_number')
        if phone:
            self.phone = phone

    def action_add_as_partner(self):
        self.ensure_one()
        if self.partner_id:
            return
        self._fetch_google_phone()
        partner = self.env['res.partner'].create({
            'name': self.name,
            'is_restaurant': True,
            'city': self.search_id.city,
            'street': self.address,
            'phone': self.phone,
            'email': self.email,
            'company_type': 'company',
            'restaurant_google_place_id': self.google_place_id,
            'restaurant_google_rating': self.rating,
            'restaurant_google_review_count': self.review_count,
            'restaurant_cuisine_type': self.cuisine_type,
            'restaurant_price_level': self.price_level,
            # Ya la teníamos (Google la da gratis en la búsqueda) -- evita que
            # base_geolocalize tenga que geocodificar de cero.
            'partner_latitude': self.latitude,
            'partner_longitude': self.longitude,
            'date_localization': fields.Date.context_today(self) if self.latitude else False,
        })
        self.write({'partner_id': partner.id, 'source': 'partner'})

    def action_mark_visto(self):
        self.write({'etiqueta': 'visto'})

    def action_mark_interesado(self):
        self.write({'etiqueta': 'interesado'})

    def action_mark_descartado(self):
        self.write({'etiqueta': 'descartado'})

    def action_rate_liked(self):
        self._set_restaurant_rating('liked')

    def action_rate_neutral(self):
        self._set_restaurant_rating('neutral')

    def action_rate_disliked(self):
        self._set_restaurant_rating('disliked')

    def _set_restaurant_rating(self, rating):
        """La valoración es del restaurante (res.partner), no de esta línea de
        búsqueda -- por eso persiste entre búsquedas futuras del mismo sitio."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_(
                'Añade este resultado como contacto antes de valorarlo -- la'
                ' valoración se guarda en la ficha del restaurante.'
            ))
        self.partner_id.restaurant_internal_rating = rating

    def action_request_quote(self):
        """Envía un email real pidiendo presupuesto, por el mecanismo de mail thread
        de Odoo (no un mail.mail suelto) -- así el mensaje queda enlazado a esta línea
        con un Message-Id real, y una respuesta del restaurante que la conserve en
        References/In-Reply-To se enlaza sola vía message_update(). Requiere email de
        contacto (solo lo tienen los resultados 'Ya en Odoo' o los Google ya
        convertidos a partner a mano, Google Places nunca devuelve email)."""
        self.ensure_one()
        email_to = self._get_quote_email_to()
        search = self.search_id
        subject = _('Petición de presupuesto — %(city)s, %(pax)s pax') % {
            'city': search.city or '',
            'pax': search.min_capacity or '?',
        }
        body_lines = [
            _('Hola,'),
            '',
            _('Somos %(company)s y estamos organizando un evento en %(city)s para'
              ' %(pax)s personas. ¿Podríais enviarnos vuestro presupuesto?') % {
                'company': self.env.company.name,
                'city': search.city or '',
                'pax': search.min_capacity or '?',
            },
        ]
        if search.notes:
            body_lines += ['', _('Notas adicionales: %s') % search.notes]
        body_lines += ['', _('Gracias,'), self.env.user.name]
        body_html = Markup('<br/>').join(Markup.escape(line) for line in body_lines)

        self.message_post(
            body=body_html,
            subject=subject,
            message_type='email',
            subtype_xmlid='mail.mt_comment',
            email_from=search.user_id.email or self.env.user.email,
            outgoing_email_to=email_to,
        )

        self.write({
            'etiqueta': 'solicitado',
            'quote_requested_date': fields.Datetime.now(),
            'quote_reminder_sent_date': False,
        })
        search.message_post_if_exists(_(
            'Presupuesto solicitado a %(name)s (%(email)s).'
        ) % {'name': self.name, 'email': email_to})

    def _get_quote_email_to(self):
        self.ensure_one()
        email_to = (self.partner_id.email or self.email or '').strip()
        if not email_to:
            raise UserError(_(
                'Este resultado no tiene email de contacto. Añádelo como contacto'
                ' (o edítalo en la ficha) antes de pedir presupuesto.'
            ))
        return email_to

    def action_send_quote_reminder(self):
        """Recordatorio de una petición sin respuesta. Mismo mecanismo de hilo que
        action_request_quote (message_post con outgoing_email_to), pero con un texto
        propio y configurable -- no repite el cuerpo de la petición original."""
        self.ensure_one()
        email_to = self._get_quote_email_to()
        search = self.search_id
        subject = _('Recordatorio: petición de presupuesto — %(city)s, %(pax)s pax') % {
            'city': search.city or '',
            'pax': search.min_capacity or '?',
        }
        text = self.env['ir.config_parameter'].sudo().get_param(
            'restagrup.quote_reminder_text',
        ) or QUOTE_REMINDER_DEFAULT_TEXT % {'company': self.env.company.name}
        body_html = Markup('<br/>').join(
            Markup.escape(line) for line in text.splitlines() + ['', self.env.user.name]
        )
        self.message_post(
            body=body_html,
            subject=subject,
            message_type='email',
            subtype_xmlid='mail.mt_comment',
            email_from=search.user_id.email or self.env.user.email,
            outgoing_email_to=email_to,
        )
        self.write({'quote_reminder_sent_date': fields.Datetime.now()})

    @api.model
    def _cron_send_quote_reminders(self):
        """Cron diario: un recordatorio por cada petición colgada que aún no lo
        tenga. Una línea sin email no debe parar al resto."""
        threshold = fields.Datetime.now() - timedelta(days=QUOTE_STALE_DAYS)
        lines = self.search([
            ('etiqueta', '=', 'solicitado'),
            ('quote_requested_date', '<=', threshold),
            ('quote_reminder_sent_date', '=', False),
        ])
        for line in lines:
            try:
                with self.env.cr.savepoint():
                    line.action_send_quote_reminder()
            except UserError as exc:
                _logger.warning(
                    'Recordatorio de presupuesto omitido para la línea %s: %s', line.id, exc,
                )

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for line in self:
            line._restagrup_classify_quote_response(msg_dict)
        return res

    def _restagrup_classify_quote_response(self, msg_dict):
        """Misma idea que purchase_order.py::_restagrup_classify_response (hoja de
        servicio) -- aquí para la respuesta a la petición de presupuesto de una línea
        de búsqueda. Nunca registra el presupuesto sola: solo extrae y dejan la
        revisión al usuario, igual que action_extract_quote_from_text."""
        self.ensure_one()
        if self.etiqueta != 'solicitado':
            return
        raw_body = msg_dict.get('body') or ''
        text = html2plaintext(raw_body).strip() if raw_body else ''
        if not text:
            return

        connector = self.env['restagrup.llm.connector']
        data, provider = connector.extract_json(EXTRACT_QUOTE_SYSTEM_PROMPT, text)
        if not data:
            return

        amount = self._restagrup_safe_float(data.get('importe'))
        vals = {}
        if amount:
            vals['quote_amount'] = amount
        if data.get('notas'):
            vals['quote_notes'] = data['notas']
        if vals:
            self.write(vals)
        self.search_id.message_post_if_exists(_(
            '%(name)s: respuesta de presupuesto recibida por email, importe extraído'
            ' por IA (%(provider)s) — revisa antes de registrar.'
        ) % {'name': self.name, 'provider': provider})

    def action_extract_quote_from_text(self):
        """Propone importe y notas leyendo el texto pegado -- nunca registra sola,
        el usuario revisa el resultado y pulsa 'Registrar' aparte (mismo patrón que
        la extracción de leads en restagrup_email_ai)."""
        self.ensure_one()
        text = (self.quote_raw_text or '').strip()
        if not text:
            raise UserError(_('Pega primero el texto de la respuesta del restaurante.'))
        connector = self.env['restagrup.llm.connector']
        data, provider = connector.extract_json(EXTRACT_QUOTE_SYSTEM_PROMPT, text)
        if data is None:
            raise UserError(_(
                'No se pudo extraer el importe automáticamente (IA no configurada o'
                ' sin respuesta) -- introduce el presupuesto a mano.'
            ))
        amount = self._restagrup_safe_float(data.get('importe'))
        if not amount:
            raise UserError(_(
                'La IA no encontró un importe claro en el texto -- revísalo e'
                ' introduce el presupuesto a mano.'
            ))
        vals = {'quote_amount': amount}
        if data.get('notas'):
            vals['quote_notes'] = data['notas']
        self.write(vals)
        self.search_id.message_post_if_exists(_(
            '%(name)s: importe extraído por IA (%(provider)s) — revisa antes de registrar.'
        ) % {'name': self.name, 'provider': provider})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search.line',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('restagrup_restaurants.view_restaurant_search_line_quote_form').id,
            'target': 'new',
        }

    @staticmethod
    def _restagrup_safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def action_view_conversation(self):
        """Abre la ficha completa (con chatter) para ver el historial de la petición
        de presupuesto y, si ya llegó, la respuesta enlazada sola por email -- el
        diálogo de "Registrar presupuesto" nunca muestra el chatter (Odoo lo oculta
        dentro de cualquier diálogo), así que hace falta esta vista aparte, a página
        completa, para poder verlo."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search.line',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_quote_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search.line',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('restagrup_restaurants.view_restaurant_search_line_quote_form').id,
            'target': 'new',
        }

    def action_register_quote(self):
        self.ensure_one()
        if not self.quote_amount:
            raise UserError(_('Indica el importe del presupuesto antes de registrarlo.'))
        self.write({'etiqueta': 'presupuesto_recibido'})
        self.search_id.message_post_if_exists(_(
            '%(name)s: presupuesto recibido — %(amount)s €.'
        ) % {'name': self.name, 'amount': self.quote_amount})
        return {'type': 'ir.actions.act_window_close'}

    def action_toggle_chosen(self):
        self.ensure_one()
        if self.search_id.chosen_line_id.id == self.id:
            self.search_id.chosen_line_id = False
            return
        if self.etiqueta != 'presupuesto_recibido':
            raise UserError(_(
                'Solo se puede elegir un restaurante con presupuesto recibido.'
                ' Pide presupuesto y regístralo antes de elegirlo.'
            ))
        self._fetch_google_phone()
        self.search_id.chosen_line_id = self.id
