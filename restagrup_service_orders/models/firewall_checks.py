# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.tools.mail import email_normalize


class CrmLeadFirewall(models.Model):
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'restagrup.firewall.mixin']

    def _restagrup_firewall_orders(self):
        searches = self.restagrup_restaurant_search_ids
        return (self.sudo().order_ids | searches.sudo().sale_order_id).filtered(lambda o: o.state != 'cancel')

    # --- pasar a presupuesto ---

    def _fw_agency_contact(self):
        if not self.partner_id and not email_normalize(self.email_from or ''):
            return _('La agencia no tiene contacto: falta el cliente o su email para enviarle la propuesta.')
        return False

    def _fw_services_complete(self):
        missing = self._restagrup_missing_request_data()
        return _('Faltan datos del servicio: %s.') % '; '.join(missing) if missing else False

    def _fw_has_option(self):
        searches = self.restagrup_restaurant_search_ids
        quoted = any(line.etiqueta == 'presupuesto_recibido' and line.quote_amount for line in searches.line_ids)
        in_order = any(line.restaurant_id for order in self._restagrup_firewall_orders() for line in order.order_line)
        if quoted or in_order:
            return False
        return _('No hay ningún restaurante con presupuesto o menú que ofrecer a la agencia.')

    # --- pasar a expediente ---

    def _fw_restaurant_chosen(self):
        searches = self.restagrup_restaurant_search_ids
        in_order = any(line.restaurant_id for order in self._restagrup_firewall_orders() for line in order.order_line)
        if any(search.chosen_line_id for search in searches) or in_order:
            return False
        return _('Todavía no hay restaurante elegido para este grupo.')

    def _fw_pax_defined(self):
        events = self.restagrup_event_ids
        if events:
            return _('Faltan los comensales de algún servicio.') if not all(events.mapped('pax')) else False
        return False if self.restagrup_pax else _('Faltan los comensales del servicio.')

    # --- cerrar expediente ---

    def _fw_service_done(self):
        dates = [e.event_date for e in self.restagrup_event_ids if e.event_date] or (
            [self.restagrup_service_date] if self.restagrup_service_date else [])
        last = max(dates) if dates else False
        if last and last >= fields.Date.context_today(self):
            return _('El último servicio todavía no ha terminado (%s).') % last.strftime('%d/%m/%Y')
        return False


class SaleOrderFirewall(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'restagrup.firewall.mixin']

    def _fw_restaurant_confirmed(self):
        sheets = self.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')
        pending = sheets.filtered(lambda po: po.restagrup_response_state != 'accepted')
        if pending:
            return _('El restaurante todavía no ha confirmado por escrito: %s.') % ', '.join(
                pending.mapped('partner_id.name'))
        return False

    def _fw_restaurant_bank(self):
        restaurants = self.order_line.mapped('restaurant_id').filtered(
            lambda r: not r.bank_ids and not r.restaurant_iban)
        if restaurants:
            return _('Falta la cuenta bancaria de: %s (hace falta para el prepago).') % ', '.join(restaurants.mapped('name'))
        return False

    def _fw_company_bank(self):
        if not self.company_id.partner_id.bank_ids:
            return _('La compañía no tiene cuenta bancaria configurada: el documento saldrá sin datos de pago.')
        return False


class PurchaseOrderFirewall(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'restagrup.firewall.mixin']

    def _fw_service_datetime(self):
        lines = self.order_line.mapped('restagrup_sale_line_id')
        if not lines or any(not line.service_date or not line.service_hour for line in lines):
            return _('Falta la fecha o la hora del servicio.')
        return False

    def _fw_restaurant_email(self):
        return False if (self.partner_id.email or '').strip() else _('El restaurante no tiene email para enviarle la confirmación.')
