# -*- coding: utf-8 -*-
from odoo import api, fields, models

RESTAURANT_RATING_SELECTION = [
    ('liked', 'Nos gustó'),
    ('neutral', 'Neutral'),
    ('disliked', 'No repetir'),
]

# Datos sin los que no se puede valorar un restaurante para un grupo (A3).
RESTAURANT_REQUIRED_FIELDS = (
    'restaurant_capacity', 'restaurant_closed_weekday', 'restaurant_language',
    'restaurant_group_manager', 'restaurant_group_mobile',
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
        help='Datos de la ficha de grupo aún sin rellenar (aforo, día de cierre, idioma, responsable y móvil).',
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

    @api.onchange('is_restaurant')
    def _onchange_is_restaurant(self):
        if self.is_restaurant and not self.company_type:
            self.company_type = 'company'
