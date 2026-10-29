# -*- coding: utf-8 -*-
from odoo import api, fields, models

INT_DEFAULTS = {
    'payment_request_days': 7,       # días antes del primer servicio para pedir el pago a la agencia
    'payment_alert_hours': 72,       # horas antes: administración avisa si no hay pago
    'restaurant_payment_hours': 48,  # horas antes: se paga a los restaurantes
    'final_pax_hours': 48,           # horas laborables antes: plazo para dar los comensales finales
    'invoice_days': 7,               # días máximos tras el último servicio para facturar
}


class RestagrupPaymentSettings(models.AbstractModel):
    """Plazos de pago. Los fija RestaGrup en Ajustes; los textos de los correos son plantillas (Plantillas de correo)."""
    _name = 'restagrup.payment.settings'
    _description = 'Plazos de pago'

    @api.model
    def value(self, key):
        raw = self.env['ir.config_parameter'].sudo().get_param('restagrup.%s' % key)
        if not raw:  # sin valor (get_param devuelve False): el de serie
            return INT_DEFAULTS[key]
        try:
            return int(raw)
        except ValueError:
            return INT_DEFAULTS[key]


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    restagrup_payment_request_days = fields.Integer(string='Pedir el pago (días antes del servicio)')
    restagrup_payment_alert_hours = fields.Integer(string='Avisar si no hay pago (horas antes)')
    restagrup_restaurant_payment_hours = fields.Integer(string='Pagar a los restaurantes (horas antes)')
    restagrup_final_pax_hours = fields.Integer(string='Comensales finales (horas laborables antes)')
    restagrup_invoice_days = fields.Integer(string='Facturar (días máx. tras el último servicio)')

    @api.model
    def get_values(self):
        res = super().get_values()
        settings = self.env['restagrup.payment.settings']
        for key in INT_DEFAULTS:
            res['restagrup_%s' % key] = settings.value(key)
        return res

    def set_values(self):
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        for key in INT_DEFAULTS:
            params.set_param('restagrup.%s' % key, str(int(getattr(self, 'restagrup_%s' % key) or INT_DEFAULTS[key])))
