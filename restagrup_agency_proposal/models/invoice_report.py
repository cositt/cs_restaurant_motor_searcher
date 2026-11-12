# -*- coding: utf-8 -*-
"""Factura a la agencia como la de su CRM (ronda de ajustes 11/11).

Una línea por servicio (fecha, «MENU Comida en "Restaurante"», precio del menú, PAX y total), la razón social de
Restagrup con su dirección y NIF, los datos de la agencia y el desglose de IVA. Solo para las facturas y abonos de
cliente: las de proveedor (restaurantes) siguen con la de serie."""
from odoo import _, api, fields, models

LEGAL_NAME_PARAM = 'restagrup.legal_name'


def service_description(event_type_name, restaurant_name):
    """«MENU Cena en "VERONA 63"», como en su CRM."""
    meal = event_type_name or _('Servicio')
    return _('MENU %(meal)s en "%(restaurant)s"', meal=meal, restaurant=restaurant_name) if restaurant_name \
        else _('MENU %s', meal)


class AccountMoveRestagrupInvoice(models.Model):
    _inherit = 'account.move'

    def _get_name_invoice_report(self):
        self.ensure_one()
        if self.move_type in ('out_invoice', 'out_refund'):
            return 'restagrup_agency_proposal.report_invoice_restagrup'
        return super()._get_name_invoice_report()

    @api.model
    def restagrup_legal_name(self, company):
        """Razón social (Ajustes > Restagrup); sin ella, el nombre de la compañía."""
        return self.env['ir.config_parameter'].sudo().get_param(LEGAL_NAME_PARAM) or company.name or ''

    def restagrup_invoice_rows(self):
        """Filas de la factura: una por línea de producto, con la fecha del servicio y el precio por persona."""
        self.ensure_one()
        rows = []
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            sale_line = line.sale_line_ids[:1]
            pax = line.quantity or 0.0
            rows.append({
                'date': sale_line.service_date and sale_line.service_date.strftime('%d/%m/%Y') or '',
                'name': line.name or '',
                'price': line.price_total / pax if pax else line.price_total,
                'pax': int(pax) if float(pax).is_integer() else pax,
                'total': line.price_total,
            })
        return rows

    def restagrup_tax_rows(self):
        """Desglose de impuestos [(«IVA 10%», importe)]. Sin impuestos en la factura, vacío (no se inventa)."""
        self.ensure_one()
        totals = {}
        sign = -1 if self.move_type == 'out_refund' else 1
        for line in self.line_ids.filtered(lambda l: l.display_type == 'tax'):
            tax = line.tax_line_id
            label = _('IVA %s%%', ('%g' % tax.amount).replace('.', ',')) if tax.amount_type == 'percent' \
                else tax.name
            totals[label] = totals.get(label, 0.0) + sign * -line.balance
        return list(totals.items())

    def restagrup_group_ref(self):
        """La referencia del grupo para la agencia (su «Grupo»): la del pedido o, si no hay, el nombre del grupo."""
        self.ensure_one()
        orders = self.invoice_line_ids.sale_line_ids.order_id
        return self.ref or orders[:1].client_order_ref or orders[:1].opportunity_id.name or ''


class SaleOrderLineInvoiceName(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_invoice_line(self, **optional_values):
        """En la factura, una línea corta por servicio en vez del menú entero (el AV se añade después)."""
        values = super()._prepare_invoice_line(**optional_values)
        if self.restaurant_id or self.service_event_type_id:
            short = service_description(self.service_event_type_id.name, self.restaurant_id.name)
            if self.restagrup_voucher:
                short = '%s\n%s' % (short, _('AV: %s') % self.restagrup_voucher)
            values['name'] = short
        return values


class ResConfigSettingsLegalName(models.TransientModel):
    _inherit = 'res.config.settings'

    restagrup_legal_name = fields.Char(
        string='Razón social (facturas)', config_parameter=LEGAL_NAME_PARAM,
        help='Sale en las facturas a las agencias con la dirección y el NIF de la compañía, p. ej. «Inversiones y'
             ' Promociones Aracil, SL». Vacío = el nombre de la compañía.')
