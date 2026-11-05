# -*- coding: utf-8 -*-
"""Vista previa del empleado sin botones de la agencia; y, aunque alguien los forzara, firmar o rechazar
desde una sesión de empleado no funciona (ver sale_order_staff_preview.py)."""
from odoo import _, http
from odoo.http import request

from odoo.addons.sale.controllers.portal import CustomerPortal


class RestagrupSalePortal(CustomerPortal):

    def _sale_order_get_page_view_values(self, order_sudo, access_token, values, history_session_key, **kwargs):
        values = super()._sale_order_get_page_view_values(
            order_sudo, access_token, values, history_session_key, **kwargs)
        portal_order = order_sudo._restagrup_portal_order(request.env.user)
        if portal_order is not order_sudo:
            values = dict(values, sale_order=portal_order, payment_amount=None)
        return values

    def _restagrup_staff_refusal(self, order_id, access_token):
        order = request.env['sale.order'].sudo().browse(order_id).exists()
        if order and not order._restagrup_customer_actions_allowed(request.env.user):
            return {'error': _('Esto lo hace la agencia desde su enlace: en la vista previa no se puede firmar ni rechazar.')}
        return None

    @http.route()
    def portal_quote_accept(self, order_id, access_token=None, name=None, signature=None):
        refusal = self._restagrup_staff_refusal(order_id, access_token)
        if refusal:
            return refusal
        return super().portal_quote_accept(order_id, access_token=access_token, name=name, signature=signature)

    @http.route()
    def portal_quote_decline(self, order_id, access_token=None, decline_message=None, **kwargs):
        if self._restagrup_staff_refusal(order_id, access_token):
            return request.redirect(request.httprequest.referrer or '/my')
        return super().portal_quote_decline(
            order_id, access_token=access_token, decline_message=decline_message, **kwargs)
