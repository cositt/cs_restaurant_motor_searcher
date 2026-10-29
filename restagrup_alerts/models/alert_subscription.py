# -*- coding: utf-8 -*-
from odoo import api, fields, models

ALERT_KINDS = ('pending_approval', 'new_request', 'quote_to_confirm', 'client_choice', 'unassigned')


class RestagrupAlertSubscription(models.Model):
    """Qué avisos recibe cada usuario. Una fila por usuario: una casilla por tipo, o «Todos»."""
    _name = 'restagrup.alert.subscription'
    _description = 'Avisos que recibe un usuario'
    _order = 'user_id'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='Usuario', required=True, ondelete='cascade', index=True,
        domain=[('share', '=', False)],
    )
    active = fields.Boolean(default=True)
    receive_all = fields.Boolean(string='Todos', help='Recibe todos los avisos, también los tipos que se añadan.')
    pending_approval = fields.Boolean(string='Pendientes de aprobar')
    new_request = fields.Boolean(string='Peticiones nuevas')
    quote_to_confirm = fields.Boolean(string='Presupuestos por confirmar')
    client_choice = fields.Boolean(string='El cliente eligió')
    unassigned = fields.Boolean(string='Sin asignar', help='Peticiones que aún no lleva nadie: para quien reparte el trabajo.')

    _user_unique = models.Constraint('unique(user_id)', 'Ese usuario ya tiene su fila de avisos.')

    @api.model
    def _subscribers(self, kind):
        """Usuarios que reciben todos los avisos de este tipo (ninguno en los avisos personales, que no se suscriben)."""
        if kind not in ALERT_KINDS:
            return self.env['res.users']
        subs = self.sudo().search(['|', ('receive_all', '=', True), (kind, '=', True)])
        return subs.user_id.filtered('active')

    def _wants(self, kind):
        self.ensure_one()
        return kind in ALERT_KINDS and (self.receive_all or self[kind])
