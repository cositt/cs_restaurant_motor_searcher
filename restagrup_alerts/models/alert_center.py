# -*- coding: utf-8 -*-
import logging

from odoo import _, api, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

BUS_TYPE = 'restagrup_alerts_refresh'
NOTIFY_OWNER_PARAM = 'restagrup.alerts_notify_owner'

# Cada aviso: qué registros cuenta (`domain`), cuáles son de un usuario como responsable (`owner`, con {uid}), qué se
# abre al pulsarlo (`open_model` + cómo pasar de los registros contados a los que se abren) y cómo se ve.
KIND_SPECS = {
    'pending_approval': {
        'model': 'restagrup.pending.mail',
        'domain': [('state', '=', 'pending')],
        'owner': ['|', ('lead_id.user_id', '=', '{uid}'), ('request_lead_id.user_id', '=', '{uid}')],
        'icon': 'fa-envelope-o',
    },
    'new_request': {
        'model': 'crm.lead',
        'domain': [('restagrup_unseen', '=', True)],
        'owner': [('user_id', '=', '{uid}')],
        'icon': 'fa-inbox',
    },
    'quote_to_confirm': {
        'model': 'restagrup.restaurant.search.line',
        'domain': [('etiqueta', '=', 'solicitado'), ('quote_amount', '!=', 0)],
        'owner': [('search_id.user_id', '=', '{uid}')],
        'icon': 'fa-cutlery',
        'open_model': 'restagrup.restaurant.search',
        'open_records': lambda lines: lines.search_id,
    },
    'client_choice': {
        'model': 'restagrup.restaurant.search',
        'domain': [('restagrup_client_choice_date', '!=', False), ('sale_order_id', '=', False)],
        'owner': [('user_id', '=', '{uid}')],
        'icon': 'fa-hand-pointer-o',
    },
}


class RestagrupAlertCenter(models.AbstractModel):
    """Calcula los avisos del usuario conectado y avisa por el bus cuando algo cambia."""
    _name = 'restagrup.alert.center'
    _description = 'Avisos Restagrup'

    @api.model
    def _notify_owner(self):
        # Al desmarcar la casilla de Ajustes Odoo borra el parámetro: sin él es «no». La instalación lo deja en «sí».
        return self.env['ir.config_parameter'].sudo().get_param(NOTIFY_OWNER_PARAM) in ('True', 'true', '1')

    @api.model
    def _title(self, kind, count):
        titles = {
            'pending_approval': (_('1 correo pendiente de aprobar'), _('%s correos pendientes de aprobar')),
            'new_request': (_('1 petición nueva sin abrir'), _('%s peticiones nuevas sin abrir')),
            'quote_to_confirm': (_('1 presupuesto de restaurante por confirmar'),
                                 _('%s presupuestos de restaurante por confirmar')),
            'client_choice': (_('1 cliente ha elegido restaurante'), _('%s clientes han elegido restaurante')),
        }
        singular, plural = titles[kind]
        return singular if count == 1 else plural % count

    @api.model
    def _domain_for(self, kind, subscription):
        """Dominio de lo que ve el usuario conectado en este aviso, o None si no le toca."""
        spec = KIND_SPECS[kind]
        if subscription and subscription._wants(kind):
            return list(spec['domain'])
        if self._notify_owner():
            owner = [term if isinstance(term, str) else (term[0], term[1], self.env.uid) for term in spec['owner']]
            return list(spec['domain']) + owner
        return None

    @api.model
    def get_alerts(self):
        """[{kind, icon, title, count, action}] de los avisos con algo pendiente para el usuario conectado."""
        subscription = self.env['restagrup.alert.subscription'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        alerts = []
        for kind, spec in KIND_SPECS.items():
            domain = self._domain_for(kind, subscription)
            if domain is None:
                continue
            try:
                records = self.env[spec['model']].search(domain)
            except AccessError:
                continue  # sin permiso sobre ese modelo: ese aviso no es para él
            if not records:
                continue
            opened = spec.get('open_records', lambda recs: recs)(records)
            title = self._title(kind, len(records))
            alerts.append({
                'kind': kind, 'icon': spec['icon'], 'title': title, 'count': len(records),
                'action': {
                    'type': 'ir.actions.act_window', 'name': title,
                    'res_model': spec.get('open_model', spec['model']),
                    'views': [[False, 'list'], [False, 'form']],
                    'domain': [('id', 'in', opened.ids)], 'target': 'current',
                },
            })
        return alerts

    @api.model
    def _ping(self, kind, owners=None):
        """Avisa por el bus a quien puede ver este tipo de aviso para que refresque los iconos. Nunca rompe lo que
        lo dispara: si el bus falla, se anota y se sigue."""
        users = self.env['restagrup.alert.subscription']._subscribers(kind)
        if owners and self._notify_owner():
            users |= owners.filtered(lambda u: u.active and not u.share)
        for user in users:
            try:
                self.env['bus.bus'].sudo()._sendone(user.partner_id, BUS_TYPE, {'kind': kind})
            except Exception:  # noqa: BLE001
                _logger.exception('No se pudo avisar a %s del cambio en los avisos', user.display_name)
