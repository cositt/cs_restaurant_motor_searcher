# -*- coding: utf-8 -*-
from odoo import _, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    restagrup_include_in_proposal = fields.Boolean(
        string='Incluir en propuesta', default=True,
        help='Desmarcar para que este restaurante/línea no salga en el PDF de propuesta'
             ' que se manda a la agencia (p.ej. si se descarta antes de confirmar).',
    )

    restagrup_gratuities = fields.Integer(
        string='Gratuidades', default=0,
        help='Comensales que no pagan (p.ej. chófer y guía). La cantidad de la línea son los que pagan;'
             ' en los documentos se muestra «pagan + gratuidades».',
    )

    def _restagrup_service_info(self):
        """Datos de una línea de servicio tal como salen en la confirmación, el bono y la hoja del restaurante."""
        self.ensure_one()
        search_line = self.restagrup_search_line_id
        menu = search_line.menu_id
        paying = int(self.product_uom_qty or 0)
        hour = self.service_hour or 0.0
        restaurant = self.restaurant_id
        address = ', '.join(part for part in (
            restaurant.street, restaurant.city, ('(%s)' % restaurant.state_id.name) if restaurant.state_id else '',
        ) if part)
        if menu:
            menu_name = menu.name
            menu_text = '\n'.join(menu._render_text(with_price=False).splitlines()[1:])
        else:
            menu_name, menu_text = '', self.name or ''
        return {
            'line': self,
            'restaurant': restaurant,
            'restaurant_name': restaurant.name or '',
            'address': address,
            'city': search_line.search_id.city or restaurant.city or '',
            'date': self.service_date.strftime('%d/%m/%Y') if self.service_date else '',
            'hour': '%02d:%02d' % (int(hour), round((hour % 1) * 60)) if hour else '',
            'service_type': self.service_event_type_id.name or '',
            'paying': paying,
            'gratuities': self.restagrup_gratuities,
            'pax_total': paying + self.restagrup_gratuities,
            'menu_name': menu_name,
            'menu_text': menu_text,
            'pvd': round(self.price_total / paying, 2) if paying else 0.0,
            'total': self.price_total,
            'cost_unit': self.restagrup_unit_cost,
            'cost_total': round(self.restagrup_unit_cost * paying, 2),
        }
