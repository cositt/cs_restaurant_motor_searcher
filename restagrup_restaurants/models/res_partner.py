# -*- coding: utf-8 -*-
from odoo import api, fields, models

RESTAURANT_RATING_SELECTION = [
    ('liked', 'Nos gustó'),
    ('neutral', 'Neutral'),
    ('disliked', 'No repetir'),
]


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
        ],
        string='Día de cierre',
    )
    restaurant_language = fields.Char(string='Idioma')
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

    @api.onchange('is_restaurant')
    def _onchange_is_restaurant(self):
        if self.is_restaurant and not self.company_type:
            self.company_type = 'company'
