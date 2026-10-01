# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_notice_ids = fields.One2many('restagrup.restaurant.notice', 'lead_id', string='Avisos a restaurantes')
    restagrup_event_count = fields.Integer(string='Eventos', compute='_compute_restagrup_summary')
    restagrup_chosen_summary = fields.Char(string='Restaurantes elegidos', compute='_compute_restagrup_summary')
    restagrup_order_total = fields.Float(string='Presupuestado (sin IVA)', compute='_compute_restagrup_summary')
    restagrup_confirmation_summary = fields.Char(string='Confirmados', compute='_compute_restagrup_summary')
    restagrup_notice_pending_count = fields.Integer(string='Avisos sin respuesta', compute='_compute_restagrup_summary')

    @api.depends(
        'restagrup_event_ids', 'restagrup_restaurant_search_ids.chosen_line_id',
        'restagrup_restaurant_search_ids.sale_order_id', 'order_ids.state', 'order_ids.amount_untaxed',
        'restagrup_notice_ids.state',
    )
    def _compute_restagrup_summary(self):
        for lead in self:
            searches = lead.restagrup_restaurant_search_ids
            orders = (lead.sudo().order_ids | searches.sudo().sale_order_id).filtered(lambda o: o.state != 'cancel')
            sheets = orders.sudo().restaurant_po_ids.filtered(lambda po: po.state != 'cancel')
            confirmed = len(sheets.filtered(lambda po: po.restagrup_response_state == 'accepted'))
            lead.restagrup_event_count = len(lead.restagrup_event_ids)
            lead.restagrup_chosen_summary = ', '.join(
                '%s (%s)' % (s.chosen_line_id.name, s.event_id.display_name or s.display_name)
                for s in searches if s.chosen_line_id
            ) or False
            lead.restagrup_order_total = sum(orders.mapped('amount_untaxed'))
            lead.restagrup_confirmation_summary = '%s/%s' % (confirmed, len(sheets)) if sheets else False
            lead.restagrup_notice_pending_count = len(lead.restagrup_notice_ids.filtered(lambda n: n.state == 'pending'))

    def _restagrup_notice_line_vals(self):
        """Un restaurante a avisar por cada búsqueda con restaurante elegido, con la hoja de servicio por la
        que saldría el aviso si ya existe."""
        self.ensure_one()
        rows = []
        for search in self.restagrup_restaurant_search_ids:
            chosen = search.chosen_line_id
            restaurant = chosen.partner_id
            if not restaurant:
                continue
            order = search.sale_order_id.sudo()
            sheet = order.restaurant_po_ids.filtered(
                lambda po: po.partner_id == restaurant and po.state != 'cancel')[:1] if order else False
            rows.append({
                'restaurant_id': restaurant.id,
                'event_label': search.event_id.display_name or search.display_name,
                'search_line_id': chosen.id,
                'po_id': sheet.id if sheet else False,
                'selected': bool((restaurant.email or '').strip()),
            })
        return rows

    def _create_notice_wizard(self):
        self.ensure_one()
        return self.env['restagrup.restaurant.notice.wizard'].create({
            'lead_id': self.id,
            'line_ids': [(0, 0, vals) for vals in self._restagrup_notice_line_vals()],
        })

    def action_notify_restaurants(self):
        self.ensure_one()
        wizard = self._create_notice_wizard()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Avisar a restaurantes'),
            'res_model': wizard._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
