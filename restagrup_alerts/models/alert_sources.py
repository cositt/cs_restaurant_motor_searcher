# -*- coding: utf-8 -*-
"""Lo que hace saltar cada aviso: marca el dato que falta y avisa por el bus cuando cambia."""
from odoo import api, fields, models

QUOTE_FIELDS = ('quote_amount', 'etiqueta')


class RestagrupPendingMail(models.Model):
    _inherit = 'restagrup.pending.mail'

    @api.model_create_multi
    def create(self, vals_list):
        mails = super().create(vals_list)
        mails._restagrup_alert_ping()
        return mails

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            self._restagrup_alert_ping()
        return res

    def _restagrup_alert_ping(self):
        if self:
            owners = self.mapped('lead_id.user_id') | self.mapped('request_lead_id.user_id')
            self.env['restagrup.alert.center']._ping('pending_approval', owners)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_unseen = fields.Boolean(
        string='Petición sin abrir', default=False, copy=False, index=True,
        help='Llegó por correo y aún no la ha abierto nadie del equipo.',
    )
    restagrup_assigned_unseen = fields.Boolean(
        string='Asignada sin abrir', default=False, copy=False, index=True,
        help='Otra persona se la ha asignado al responsable y él aún no ha abierto la ficha.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [{'restagrup_assigned_unseen': self._restagrup_assigned_by_other(vals['user_id']), **vals}
                     if vals.get('user_id') else vals for vals in vals_list]
        leads = super().create(vals_list)
        center = self.env['restagrup.alert.center']
        if leads.filtered('restagrup_assigned_unseen'):
            center._ping('assigned', leads.filtered('restagrup_assigned_unseen').user_id)
        if leads.filtered(lambda lead: not lead.user_id):
            center._ping('unassigned')
        return leads

    def _restagrup_assigned_by_other(self, user_id):
        return bool(user_id) and user_id != self.env.uid

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        lead = super().message_new(msg_dict, custom_values=custom_values)
        lead.restagrup_unseen = True
        return lead

    def write(self, vals):
        reassigned = 'user_id' in vals and self.filtered(lambda lead: lead.user_id.id != vals['user_id'])
        previous_owners = reassigned.user_id if reassigned else self.env['res.users']
        if reassigned:
            reassigned.write({
                'restagrup_assigned_unseen': self._restagrup_assigned_by_other(vals['user_id'])})
        res = super().write(vals)
        center = self.env['restagrup.alert.center']
        if 'restagrup_unseen' in vals or ('user_id' in vals and any(self.mapped('restagrup_unseen'))):
            center._ping('new_request', self.user_id)
        if reassigned:
            center._ping('assigned', previous_owners | reassigned.user_id)
            center._ping('unassigned')
        return res

    def web_read(self, specification):
        # Solo la ficha de la petición pide este campo (va invisible en el formulario): abrirla la da por vista.
        # Leer el lead desde otro registro (su nombre en un campo relacionado) no cuenta.
        opened = len(self) == 1 and 'restagrup_unseen' in specification and not self.env.user.share
        unseen = self.filtered('restagrup_unseen') if opened else self.browse()
        if unseen:
            unseen.sudo().restagrup_unseen = False
        mine = self.filtered(lambda lead: lead.restagrup_assigned_unseen and lead.user_id == self.env.user) \
            if opened else self.browse()
        if mine:
            mine.sudo().restagrup_assigned_unseen = False
            self.env['restagrup.alert.center']._ping('assigned', self.env.user)
        return super().web_read(specification)


class RestaurantSearchLine(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in QUOTE_FIELDS):
            self.env['restagrup.alert.center']._ping('quote_to_confirm', self.mapped('search_id.user_id'))
        return res


class RestaurantSearch(models.Model):
    _inherit = 'restagrup.restaurant.search'

    restagrup_client_choice_date = fields.Datetime(
        string='Elegido por el cliente', copy=False, readonly=True,
        help='Cuándo eligió el cliente este restaurante desde el portal de la comparativa.',
    )

    def _restagrup_mark_client_choice(self):
        """El cliente acaba de elegir desde el portal: queda marcado hasta que se cree el presupuesto de venta."""
        self.write({'restagrup_client_choice_date': fields.Datetime.now()})

    def write(self, vals):
        if 'chosen_line_id' in vals and not vals['chosen_line_id']:
            vals = dict(vals, restagrup_client_choice_date=False)
        res = super().write(vals)
        if any(field in vals for field in ('restagrup_client_choice_date', 'sale_order_id', 'chosen_line_id')):
            self.env['restagrup.alert.center']._ping('client_choice', self.user_id)
        return res
