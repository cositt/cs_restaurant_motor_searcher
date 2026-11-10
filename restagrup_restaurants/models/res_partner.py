# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .exchange import CURRENCY_SELECTION

LOCATION_TYPE_SELECTION = [
    ('centro', 'Centro'),
    ('alrededores', 'Alrededores'),
    ('carretera', 'Carretera'),
]

RESTAURANT_RATING_SELECTION = [
    ('liked', 'Nos gustó'),
    ('neutral', 'Neutral'),
    ('disliked', 'No repetir'),
]

# Datos sin los que no se puede valorar un restaurante para un grupo (A3).
# Lo que de verdad hace falta para trabajar con un restaurante (ronda de ajustes 09/11): aforo e idioma ya no.
RESTAURANT_REQUIRED_FIELDS = (
    'restaurant_closed_weekday', 'restaurant_group_manager', 'restaurant_group_mobile', 'restaurant_iban',
)
# Cómo se pide cada dato en el correo al restaurante (texto de Conchita).
RESTAURANT_REQUEST_LABELS = (
    (('restaurant_closed_weekday',), 'Día de cierre.'),
    (('restaurant_group_manager', 'restaurant_group_mobile'), 'Responsable de reservas de grupos y su móvil.'),
    (('restaurant_iban',), 'Cuenta bancaria para el prepago en caso de confirmación.'),
)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_restaurant = fields.Boolean(
        string='Es restaurante', index=True, default=False,
        help='Marca este contacto como restaurante para el buscador de grupos.',
    )
    restaurant_capacity = fields.Integer(string='Aforo (grupos)')
    restaurant_bus_parking = fields.Boolean(string='Parking de autobús', default=False)
    restaurant_closed_weekday = fields.Selection(
        selection=[
            ('mon', 'Lunes'), ('tue', 'Martes'), ('wed', 'Miércoles'),
            ('thu', 'Jueves'), ('fri', 'Viernes'), ('sat', 'Sábado'), ('sun', 'Domingo'),
            ('none', 'Sin día de cierre'),
        ],
        string='Día de cierre',
        help="'Sin día de cierre' = abre todos los días. Vacío = dato aún sin rellenar.",
    )
    restaurant_language = fields.Char(string='Idioma')
    restaurant_gratuities = fields.Char(
        string='Gratuidades', help='Condiciones de gratuidad para grupos, p. ej. «1 por cada 25».',
    )
    restaurant_group_manager = fields.Char(string='Responsable de grupos')
    restaurant_group_mobile = fields.Char(string='Móvil del responsable')
    restaurant_preferred_channel = fields.Selection(
        selection=[('email', 'Email'), ('whatsapp', 'WhatsApp')],
        string='Canal preferido', default='email',
    )
    restaurant_iban = fields.Char(string='Cuenta bancaria')
    # Datos generales como en el CRM de Restagrup (notas de Conchita 05/11).
    restaurant_maps_url = fields.Char(string='Enlace a Google Maps')
    restaurant_zone = fields.Char(string='Zona', help='Barrio o zona de la ciudad (p. ej. «Triana», «Centro histórico»).')
    restaurant_location_type = fields.Selection(LOCATION_TYPE_SELECTION, string='Ubicación')
    restaurant_has_contract = fields.Boolean(string='Tiene contrato')
    restaurant_currency_code = fields.Selection(
        CURRENCY_SELECTION, string='Moneda', default='EUR', required=True,
        help='En la que cobra el restaurante. Sus menús se apuntan en esta moneda y se pasan a euros con el cambio'
             ' del Banco Central Europeo.',
    )
    restaurant_currency_id = fields.Many2one(
        'res.currency', string='Moneda del restaurante', compute='_compute_restaurant_currency_id')
    restaurant_avg_carta_price = fields.Monetary(
        string='Precio medio carta', currency_field='restaurant_currency_id')
    restaurant_min_menu_price = fields.Monetary(
        string='Precio mín. menú', currency_field='restaurant_currency_id')
    restaurant_weekend_menu_price = fields.Monetary(
        string='Precio menú fin de semana', currency_field='restaurant_currency_id')
    restaurant_direct_contact = fields.Char(string='Contacto directo')
    restaurant_cuisine_type = fields.Char(string='Tipo de cocina')
    restaurant_price_level = fields.Selection(
        selection=[('1', '€'), ('2', '€€'), ('3', '€€€'), ('4', '€€€€')],
        string='Nivel de precio',
    )
    restaurant_suitable_corporate = fields.Boolean(string='Apto corporativo', default=False)
    restaurant_suitable_school = fields.Boolean(string='Apto escolar', default=False)
    restaurant_suitable_family = fields.Boolean(string='Apto familiar', default=False)
    restaurant_internal_notes = fields.Text(string='Notas internas')
    restaurant_internal_rating = fields.Selection(
        selection=RESTAURANT_RATING_SELECTION, string='Valoración interna',
        help='Valoración propia del equipo tras trabajar con este restaurante --'
             ' no tiene relación con el rating de Google.',
    )
    restaurant_google_place_id = fields.Char(string='Google Place ID', index=True, copy=False)
    restaurant_google_rating = fields.Float(string='Rating Google')
    restaurant_google_review_count = fields.Integer(string='Nº reseñas Google')

    restaurant_missing_fields = fields.Char(
        string='Datos que faltan', compute='_compute_restaurant_missing_fields',
        help='Datos de la ficha de grupo aún sin rellenar (aforo, día de cierre, idioma, responsable, móvil y cuenta bancaria).',
    )
    restaurant_is_incomplete = fields.Boolean(
        string='Ficha incompleta', compute='_compute_restaurant_missing_fields',
    )

    restaurant_margin_custom = fields.Boolean(
        string='Margen propio',
        help='Si está marcado, a este restaurante se le aplica su propio margen de beneficio en lugar del general.',
    )
    restaurant_margin_percent = fields.Float(
        string='Margen de beneficio (%)', digits=(16, 2),
        help='Se suma al precio del restaurante para sacar el precio al cliente. Solo se usa con «Margen propio».',
    )
    restaurant_menu_ids = fields.One2many(
        'restagrup.restaurant.menu', 'partner_id', string='Menús',
    )
    restaurant_menu_count = fields.Integer(
        string='Nº de menús', compute='_compute_restaurant_menu_count',
    )

    @api.depends('restaurant_menu_ids')
    def _compute_restaurant_menu_count(self):
        for partner in self:
            partner.restaurant_menu_count = len(partner.restaurant_menu_ids)

    @api.depends('is_restaurant', *RESTAURANT_REQUIRED_FIELDS)
    def _compute_restaurant_missing_fields(self):
        for partner in self:
            missing = partner._restaurant_missing_labels() if partner.is_restaurant else []
            partner.restaurant_missing_fields = ', '.join(missing)
            partner.restaurant_is_incomplete = bool(missing)

    def _restaurant_missing_labels(self):
        """Etiquetas de los datos obligatorios de la ficha que están vacíos. El parking no cuenta: un
        booleano no distingue «no hay» de «sin rellenar»."""
        self.ensure_one()
        return [self._fields[name].string for name in RESTAURANT_REQUIRED_FIELDS if not self[name]]

    def _restaurant_request_labels(self):
        """Los datos que faltan, redactados para el correo que se los pide al restaurante."""
        self.ensure_one()
        return [label for names, label in RESTAURANT_REQUEST_LABELS if any(not self[name] for name in names)]

    @api.onchange('is_restaurant')
    def _onchange_is_restaurant(self):
        if self.is_restaurant and not self.company_type:
            self.company_type = 'company'


# Ficha del restaurante (notas de Conchita 05/11): Menús lo primero, luego sus datos, y fuera lo que no usan.
RESTAURANT_FIRST_PAGES = ('restaurant_menu_catalog', 'restaurant')
PAGES_HIDDEN_FOR_RESTAURANTS = (
    'sales_purchases', 'accounting', 'accounting_disabled', 'geo_location', 'internal_notes',
    'restaurant_menus',  # «Menús de producto (avanzado)»: los menús de verdad están en «Menús»
)


class ResPartnerRestaurantCurrency(models.Model):
    _inherit = 'res.partner'

    @api.depends('restaurant_currency_code')
    def _compute_restaurant_currency_id(self):
        exchange = self.env['restagrup.exchange']
        for partner in self:
            partner.restaurant_currency_id = exchange.currency_by_code(partner.restaurant_currency_code or 'EUR')


class ResPartnerRestaurantForm(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        """Se hace aquí y no con xpath porque algunas pestañas (p. ej. «Asignación de socio») las añaden
        módulos que no son dependencia nuestra: si no están, simplemente no se tocan."""
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form':
            for notebook in arch.xpath("//sheet/notebook[page[@name='restaurant_menu_catalog']]"):
                _restaurant_pages_first(notebook)
        return arch, view


def _restaurant_pages_first(notebook):
    for name in PAGES_HIDDEN_FOR_RESTAURANTS:
        for page in notebook.xpath("./page[@name='%s']" % name):
            current = page.get('invisible')
            page.set('invisible', '(%s) or is_restaurant' % current if current else 'is_restaurant')
    for name in reversed(RESTAURANT_FIRST_PAGES):
        for page in notebook.xpath("./page[@name='%s']" % name):
            notebook.remove(page)
            notebook.insert(0, page)
    # Al abrir un restaurante, la pestaña Menús; en el resto, como siempre (Contactos, la primera visible).
    for page in notebook.xpath('./page[@autofocus]'):
        del page.attrib['autofocus']
    for page in notebook.xpath("./page[@name='restaurant_menu_catalog']"):
        page.set('autofocus', 'autofocus')
