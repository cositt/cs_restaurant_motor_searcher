# -*- coding: utf-8 -*-
from odoo import api, fields, models

INT_DEFAULTS = {
    'payment_request_days': 7,       # días antes del primer servicio para pedir el pago a la agencia
    'payment_alert_hours': 72,       # horas antes: administración avisa si no hay pago
    'restaurant_payment_hours': 48,  # horas antes: se paga a los restaurantes
    'final_pax_hours': 48,           # horas laborables antes: plazo para dar los comensales finales
    'invoice_days': 7,               # días máximos tras el último servicio para facturar
}
TEXT_DEFAULTS = {
    'payment_request_text': (
        'Hola {agencia}, se acerca la fecha de vuestro servicio. Os pedimos que nos enviéis la transferencia del '
        '100 % de la reserva y el justificante de pago para poder emitir el bono de agencia. Los datos bancarios '
        'están en la confirmación de reserva. Gracias.'),
    'payment_urgent_text': (
        'Hola {agencia}, debido a la proximidad del servicio necesitamos recibir el justificante de pago para '
        'poder enviaros el bono de agencia.'),
}


class RestagrupPaymentSettings(models.AbstractModel):
    """Plazos y textos de pago. Los fija RestaGrup en Ajustes y los lleva su equipo de administración."""
    _name = 'restagrup.payment.settings'
    _description = 'Plazos y textos de pago'

    @api.model
    def value(self, key):
        raw = self.env['ir.config_parameter'].sudo().get_param('restagrup.%s' % key)
        if not raw:  # sin valor (get_param devuelve False): el de serie
            return INT_DEFAULTS[key]
        try:
            return int(raw)
        except ValueError:
            return INT_DEFAULTS[key]

    @api.model
    def text(self, key):
        raw = self.env['ir.config_parameter'].sudo().get_param('restagrup.%s' % key)
        return raw if raw and raw.strip() else TEXT_DEFAULTS[key]


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    restagrup_payment_request_days = fields.Integer(string='Pedir el pago (días antes del servicio)')
    restagrup_payment_alert_hours = fields.Integer(string='Avisar si no hay pago (horas antes)')
    restagrup_restaurant_payment_hours = fields.Integer(string='Pagar a los restaurantes (horas antes)')
    restagrup_final_pax_hours = fields.Integer(string='Comensales finales (horas laborables antes)')
    restagrup_invoice_days = fields.Integer(string='Facturar (días máx. tras el último servicio)')
    restagrup_payment_request_text = fields.Text(string='Texto: pedir el pago')
    restagrup_payment_urgent_text = fields.Text(string='Texto: recordatorio urgente')

    @api.model
    def get_values(self):
        res = super().get_values()
        settings = self.env['restagrup.payment.settings']
        for key in INT_DEFAULTS:
            res['restagrup_%s' % key] = settings.value(key)
        for key in TEXT_DEFAULTS:
            res['restagrup_%s' % key] = settings.text(key)
        return res

    def set_values(self):
        super().set_values()
        params = self.env['ir.config_parameter'].sudo()
        for key in INT_DEFAULTS:
            params.set_param('restagrup.%s' % key, str(int(getattr(self, 'restagrup_%s' % key) or INT_DEFAULTS[key])))
        for key in TEXT_DEFAULTS:
            params.set_param('restagrup.%s' % key, getattr(self, 'restagrup_%s' % key) or TEXT_DEFAULTS[key])
