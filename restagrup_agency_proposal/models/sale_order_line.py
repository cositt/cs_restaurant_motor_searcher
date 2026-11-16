# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    restagrup_include_in_proposal = fields.Boolean(
        string='Incluir en propuesta', default=True,
        help='Desmarcar para que este restaurante/línea no salga en el PDF de propuesta'
             ' que se manda a la agencia (p.ej. si se descarta antes de confirmar).',
    )

    restagrup_gratuities = fields.Integer(
        string='Gratuidades', default=0,
        help='Comensales que no paga la agencia (p.ej. chófer y guía). La cantidad de la línea son los que pagan;'
             ' en los documentos se muestra «pagan + gratuidades». Al cambiarlas se ajusta la cantidad para que el'
             ' total no varíe (reunión 13/11: los 55 que pide la agencia ya las incluyen). El restaurante cobra'
             ' el total.',
    )

    restagrup_voucher = fields.Char(
        string='AV / voucher / localizador', copy=False,
        help='La referencia de la agencia para este servicio. Sale en la confirmación, en el bono y en la factura.',
    )

    def restagrup_diners_text(self):
        """«53 + 2 gratuidades» en el PDF de propuesta, junto a los comensales (correo de Conchita 16/11)."""
        self.ensure_one()
        qty = self.product_uom_qty
        paying = int(qty) if float(qty).is_integer() else qty
        if not self.restagrup_gratuities:
            return str(paying)
        return _('%(paying)s + %(gratuities)s gratuidades') % {
            'paying': paying, 'gratuities': self.restagrup_gratuities}

    @api.model_create_multi
    def create(self, vals_list):
        """Una línea que sale de un servicio con gratuidades nace con ellas restadas de la cantidad (P3)."""
        SearchLine = self.env['restagrup.restaurant.search.line']
        new_vals_list = []
        for vals in vals_list:
            event = SearchLine.browse(vals.get('restagrup_search_line_id')).search_id.event_id
            gratuities = event.gratuities if event else 0
            if gratuities and 'restagrup_gratuities' not in vals and vals.get('product_uom_qty'):
                vals = dict(vals, restagrup_gratuities=gratuities,
                            product_uom_qty=max(vals['product_uom_qty'] - gratuities, 0))
            new_vals_list.append(vals)
        return super().create(new_vals_list)

    def write(self, vals):
        """Cambiar solo las gratuidades mueve comensales de «pagan» a «gratis»: el total se mantiene."""
        if 'restagrup_gratuities' not in vals or 'product_uom_qty' in vals:
            return super().write(vals)
        new = vals['restagrup_gratuities'] or 0
        for line in self:
            qty = max(line.product_uom_qty - (new - line.restagrup_gratuities), 0)
            super(SaleOrderLine, line).write(dict(vals, product_uom_qty=qty))
        return True

    @api.onchange('restagrup_gratuities')
    def _onchange_restagrup_gratuities(self):
        for line in self:
            delta = (line.restagrup_gratuities or 0) - (line._origin.restagrup_gratuities or 0)
            if delta:
                line.product_uom_qty = max(line.product_uom_qty - delta, 0)

    def _restagrup_restaurant_qty(self):
        """El restaurante cobra todos los comensales, gratuidades incluidas (reunión 13/11, P3)."""
        return super()._restagrup_restaurant_qty() + (self.restagrup_gratuities or 0)

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        if self.restagrup_voucher:
            values['name'] = '%s\n%s' % (values.get('name') or self.name or '', _('AV: %s') % self.restagrup_voucher)
        return values

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
        chosen = (search_line.agency_choice_notes or '').strip()
        if menu and chosen:
            # Ronda 11/11: con platos elegidos, solo lo elegido y lo que el menú incluye siempre (pan, bebidas…).
            menu_name = menu.name
            menu_text = '\n'.join([_('Platos elegidos:'), chosen] + menu._always_included())
        elif menu:
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
            'voucher': self.restagrup_voucher or '',
            # Restaurante en otra moneda: su precio en lo que cobra él, con el cambio de la reserva.
            'fx_code': self.restagrup_fx_currency_code or '',
            'cost_unit_fx': round(self.restagrup_unit_cost / self.restagrup_fx_rate, 2) if (
                self.restagrup_fx_currency_code and self.restagrup_fx_rate) else 0.0,
            'pax_total': paying + self.restagrup_gratuities,
            'menu_name': menu_name,
            'menu_text': menu_text,
            'notes': self._restagrup_third_party_notes(),
            'pvd': round(self.price_total / paying, 2) if paying else 0.0,
            'total': self.price_total,
            'cost_unit': self.restagrup_unit_cost,
            'cost_total': round(self.restagrup_unit_cost * paying, 2),
        }
