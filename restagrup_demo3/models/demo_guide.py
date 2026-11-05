# -*- coding: utf-8 -*-
"""Soporte de la pantalla «Guía de la demo 3»: estado de cada paso del recorrido completo de un grupo y reinicio.
Las simulaciones de correo están en demo_simulate.py."""
from odoo import _, api, models
from odoo.exceptions import UserError

AGENCY_FROM = 'Lucía Prieto <lucia@costaviajes.demo>'
AGENCY_EMAIL = 'lucia@costaviajes.demo'
AGENCY_NAME = 'Costa Viajes Ibéricos'
ENABLED_PARAM = 'restagrup_demo3.enabled'
SEEN_PARAM = 'restagrup_demo3.seen.%s'  # pasos de «mirar» (no dejan rastro en los datos): id de la petición
SEEN_STEPS = ('menus', 'control')
# Los tres restaurantes a los que se pide presupuesto: nombre -> precio por persona que contestan
QUOTE_RESTAURANTS = {
    'Taberna del Patio Andaluz': 26.0,
    'Casa Giralda Grupos': 28.0,
    'Bodega San Telmo': 24.5,
}
PAYMENT_KINDS = ('agency_payment_request', 'agency_payment_urgent')


class RestagrupDemo3Guide(models.AbstractModel):
    _name = 'restagrup.demo3.guide'
    _description = 'Guía de la demo 3'

    # --- registros del recorrido -------------------------------------------------------------------------------

    @api.model
    def _lead(self):
        return self.env['crm.lead'].sudo().with_context(active_test=False).search(
            [('email_from', 'ilike', AGENCY_EMAIL)], order='id desc', limit=1)

    @api.model
    def _rg_search(self, lead=None):
        lead = self._lead() if lead is None else lead
        return lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else self.env['restagrup.restaurant.search']

    @api.model
    def _quote_lines(self, search):
        return search.line_ids.filtered(lambda line: line.name in QUOTE_RESTAURANTS)

    @api.model
    def _rg_order(self, search=None):
        search = self._rg_search() if search is None else search
        return search.sale_order_id.sudo() if search else self.env['sale.order']

    @api.model
    def _rg_sheet(self, order=None):
        order = self._rg_order() if order is None else order
        return order.restaurant_po_ids.sudo().filtered(lambda po: po.state != 'cancel')[:1]

    @api.model
    def _restaurants(self):
        return self.env['res.partner'].sudo().search(
            [('name', 'in', list(QUOTE_RESTAURANTS)), ('is_restaurant', '=', True)])

    @api.model
    def _pending_for(self, kinds, order=None, sheet=None):
        domain = [('kind', 'in', list(kinds))]
        if order is not None:
            domain.append(('sale_order_id', '=', order.id))
        if sheet is not None:
            domain.append(('purchase_order_id', '=', sheet.id))
        return self.env['restagrup.pending.mail'].sudo().search(domain)

    @api.model
    def _require(self, record, message):
        if not record:
            raise UserError(message)
        return record

    # --- estado de los pasos -----------------------------------------------------------------------------------

    @api.model
    def _seen(self, step, lead):
        return bool(lead) and self.env['ir.config_parameter'].sudo().get_param(SEEN_PARAM % step) == str(lead.id)

    @api.model
    def mark_seen(self, step):
        """Pasos de «mirar» (fichas y menús, configuración): abrirlos ya cuenta como hecho."""
        lead = self._lead()
        if lead and step in SEEN_STEPS:
            self.env['ir.config_parameter'].sudo().set_param(SEEN_PARAM % step, str(lead.id))
        return True

    @api.model
    def _done_request(self, lead, search, lines):
        asked = bool(lead) and lead.restagrup_data_request_count >= 1
        pending = self.env['restagrup.pending.mail'].sudo().search_count(
            [('request_lead_id', '=', lead.id)]) if lead else 0
        answered = len(lines.filtered(lambda l: l.quote_amount > 0)) >= len(QUOTE_RESTAURANTS)
        ai_menus = self.env['restagrup.restaurant.menu'].sudo().search_count(
            [('partner_id', 'in', self._restaurants().ids), ('ai_pending_review', '=', True)])
        return {
            'email': bool(lead),
            'assign': bool(lead) and bool(lead.user_id),
            'ask': bool(pending) or asked,
            'approve': asked,
            'reply': asked and not lead._restagrup_missing_request_data(),
            'menus': bool(search) or self._seen('menus', lead),
            'search': bool(search),
            'request': len(lines.filtered('quote_requested_date')) >= len(QUOTE_RESTAURANTS),
            'answers': answered,
            'menu_review': answered and not ai_menus,
            'confirm': len(lines.filtered(lambda l: l.etiqueta == 'presupuesto_recibido')) >= len(QUOTE_RESTAURANTS),
        }

    @api.model
    def _done_file(self, lead, search, order, sheet):
        sold = bool(order) and order.state == 'sale'
        claims = self._pending_for(['restaurant_invoice_claim'], sheet=sheet) if sheet else False
        return {
            'proposal': bool(lead) and lead.restagrup_stage_key in ('presupuesto', 'expediente', 'cerrado'),
            'choose': bool(search) and bool(search.chosen_line_id),
            'order': bool(order),
            'sign': sold,
            'docs': sold and any(order.order_line.mapped('restagrup_gratuities')),
            'sheets_sent': bool(sheet) and sheet.state in ('sent', 'purchase'),
            'restaurant_ok': bool(sheet) and sheet.restagrup_response_state == 'accepted',
            'daily': sold and bool(self._pending_for(PAYMENT_KINDS, order=order)),
            'payments_sent': sold and bool(order.restagrup_payment_requested_date or order.restagrup_payment_urgent_date)
            and bool(sheet.restagrup_bank_request_date),
            'agency_paid': sold and order.restagrup_paid,
            'restaurant_paid': bool(sheet) and sheet.restagrup_restaurant_paid,
            'service_done': bool(sheet) and (bool(claims) or sheet.restagrup_invoice_claim_level >= 1),
            'invoice_ok': bool(sheet) and sheet.restagrup_invoice_received,
            'agency_invoice': sold and order.restagrup_invoice_sent,
            'closed': bool(lead) and lead.restagrup_stage_key == 'cerrado',
            'control': self._seen('control', lead),
        }

    @api.model
    def get_state(self):
        """Qué paso está hecho y los ids a los que enlazar. Se vuelve a calcular cada vez que se abre la guía."""
        lead = self._lead()
        search = self._rg_search(lead)
        lines = self._quote_lines(search) if search else self.env['restagrup.restaurant.search.line']
        order = self._rg_order(search)
        sheet = self._rg_sheet(order) if order else self.env['purchase.order']
        done = {**self._done_request(lead, search, lines), **self._done_file(lead, search, order, sheet)}
        return {
            'done': done,
            'lead_id': lead.id or False,
            'search_id': search.id or False,
            'order_id': order.id or False,
            'sheet_id': sheet.id or False,
            'search_portal_url': lead._restagrup_proposal_portal_url()
            if lead and lead.restagrup_proposal_token else False,
            'order_portal_url': order.get_portal_url() if order else False,
        }

    # --- reinicio ------------------------------------------------------------------------------------------------

    @api.model
    def _remove_invoices(self, orders, sheets):
        """Facturas que se hayan creado en el recorrido (a la agencia o del restaurante): si no, bloquean el
        borrado de la agencia. Las validadas se pasan antes a borrador."""
        moves = (orders.invoice_ids | sheets.invoice_ids).sudo()
        moves.filtered(lambda move: move.state != 'draft').button_draft()
        moves.with_context(force_delete=True).unlink()

    @api.model
    def reset_demo(self):
        """Quita solo lo del recorrido (la agencia Costa Viajes, su petición y lo que colgaba de ella, los menús que
        creó la IA y las cuentas bancarias de los tres restaurantes). Los documentos de ejemplo de las listas se
        quedan. Solo en la BD de la demo 3 (parámetro restagrup_demo3.enabled = 1)."""
        if self.env['ir.config_parameter'].sudo().get_param(ENABLED_PARAM) != '1':
            raise UserError(_('El reinicio solo está disponible en la base de datos de la demo 3.'))
        env = self.env
        lead = self._lead()
        searches = lead.restagrup_restaurant_search_ids.sudo() if lead else env['restagrup.restaurant.search']
        orders = (searches.sale_order_id | lead.sudo().order_ids) if lead else env['sale.order']
        sheets = orders.restaurant_po_ids.sudo().with_context(active_test=False)
        pending = env['restagrup.pending.mail'].sudo().search(
            ['|', '|', ('sale_order_id', 'in', orders.ids), ('purchase_order_id', 'in', sheets.ids),
             ('request_lead_id', '=', lead.id or 0)])
        pending.unlink()
        self._remove_invoices(orders, sheets)
        sheets.filtered(lambda po: po.state != 'cancel').button_cancel()
        sheets.unlink()
        orders.sudo().filtered(lambda so: so.state != 'cancel')._action_cancel()
        orders.sudo().unlink()
        if lead:
            env['restagrup.restaurant.notice'].sudo().search([('lead_id', '=', lead.id)]).unlink()
        searches.unlink()
        if lead:
            lead.sudo().with_context(active_test=False).unlink()
        restaurants = self._restaurants()
        env['restagrup.restaurant.menu'].sudo().with_context(active_test=False).search(
            [('partner_id', 'in', restaurants.ids), ('ai_pending_review', '=', True)]).unlink()
        env['restagrup.restaurant.menu'].sudo().with_context(active_test=False).search(
            [('partner_id', 'in', restaurants.ids), ('source_line_id', '!=', False)]).unlink()
        env['res.partner.bank'].sudo().search([('partner_id', 'in', restaurants.ids)]).unlink()
        env['res.partner'].sudo().search([('email', 'ilike', AGENCY_EMAIL), ('is_restaurant', '=', False)]).unlink()
        env['res.partner'].sudo().search([('name', '=', AGENCY_NAME), ('is_company', '=', True)]).unlink()
        for step in SEEN_STEPS:
            env['ir.config_parameter'].sudo().set_param(SEEN_PARAM % step, False)
        return True
