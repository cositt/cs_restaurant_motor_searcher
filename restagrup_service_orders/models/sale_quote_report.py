# -*- coding: utf-8 -*-
"""Datos del PDF del presupuesto con el formato de Restagrup: cabecera del grupo y un bloque por servicio
con el restaurante, el menú y el precio neto por persona (como el que enviaban desde su CRM)."""
from odoo import models


def _hour_text(hour):
    if not hour:
        return ''
    hours, minutes = divmod(round(hour * 60), 60)
    return '%02d:%02d' % (hours, minutes)


class SaleOrderQuoteReport(models.Model):
    _inherit = 'sale.order'

    def _restagrup_quote_header(self):
        """Filas de la cabecera: (etiqueta, valor)."""
        self.ensure_one()
        contact = self.partner_id
        agency = contact.commercial_partner_id
        lead = self.opportunity_id
        return [
            ('DOCUMENTO Nº', self.name),
            ('GRUP. REF', lead.name or self.origin or ''),
            ('AGENCIA', agency.name or ''),
            ('TELÉFONO', agency.phone or contact.phone or ''),
            ('NOMBRE', contact.name if contact != agency else (lead.contact_name or '')),
            ('CONTACTO', contact.email or agency.email or ''),
            ('AGENTE RESTAGRUP', self.user_id.name or ''),
        ]

    def _restagrup_quote_services(self):
        """Un bloque por línea de servicio, por fecha y hora."""
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty)
        lines = lines.sorted(lambda l: (l.service_date or l.order_id.date_order.date(), l.service_hour, l.id))
        return [self._restagrup_quote_service(index, line) for index, line in enumerate(lines, start=1)]

    def _restagrup_quote_service(self, index, line):
        restaurant = line.restaurant_id
        search_line = line.restagrup_search_line_id
        menu = search_line.menu_id
        gratuities = line['restagrup_gratuities'] if 'restagrup_gratuities' in line._fields else 0
        address = ', '.join(part for part in (restaurant.street, restaurant.zip, restaurant.city) if part)
        return {
            'title': '%sº Servicio - %s - %s - PAX: %s' % (
                index, search_line.search_id.city or restaurant.city or '',
                line.service_date.strftime('%d/%m/%Y') if line.service_date else '',
                int(line.product_uom_qty + (gratuities or 0))),
            'restaurant': restaurant.name or '',
            'address': address,
            'service_type': line.service_event_type_id.name or '',
            'hour': _hour_text(line.service_hour),
            'menu_text': menu._render_text(with_price=False) if menu else (line.name or ''),
            'price_pp': line.price_total / line.product_uom_qty,
        }
