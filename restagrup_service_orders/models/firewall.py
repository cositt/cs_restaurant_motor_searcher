# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

TRIGGERS = [
    ('pass_to_quote', 'Pasar a presupuesto'),
    ('pass_to_file', 'Pasar a expediente'),
    ('close_file', 'Cerrar expediente'),
    ('confirm_agency', 'Confirmación a la agencia'),
    ('confirm_restaurant', 'Confirmación al restaurante'),
]


class FirewallCheck(models.Model):
    """Cortafuegos: una comprobación que se hace antes de un paso importante. RestaGrup decide cuáles están
    activas y si solo avisan (y consultan) o impiden continuar."""
    _name = 'restagrup.firewall.check'
    _description = 'Comprobación del cortafuegos'
    _order = 'trigger, sequence, id'

    code = fields.Char(string='Código', required=True, readonly=True, copy=False)
    name = fields.Char(string='Qué se comprueba', required=True, translate=True)
    trigger = fields.Selection(TRIGGERS, string='Antes de', required=True, readonly=True)
    mode = fields.Selection(
        [('warn', 'Avisar y consultar'), ('block', 'Impedir continuar')], string='Si falta', default='warn',
        required=True,
        help='Avisar y consultar: se muestra lo que falta y la persona decide si continúa (queda anotado en el'
             ' chatter). Impedir continuar: no deja avanzar hasta que se resuelva.',
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _code_unique = models.Constraint('unique(code)', 'Ya existe una comprobación con ese código.')


class FirewallMixin(models.AbstractModel):
    _name = 'restagrup.firewall.mixin'
    _description = 'Motor del cortafuegos'

    def _restagrup_firewall_issues(self, trigger):
        """Lo que no pasa las comprobaciones activas de este paso: [{'check': registro, 'message': texto}].
        Cada comprobación `code` la implementa el modelo como `_fw_<code>()`, que devuelve el aviso o False."""
        self.ensure_one()
        issues = []
        checks = self.env['restagrup.firewall.check'].search([('trigger', '=', trigger), ('active', '=', True)])
        for check in checks:
            method = getattr(self, '_fw_%s' % check.code, None)
            message = method() if method else False
            if message:
                issues.append({'check': check, 'message': message})
        return issues

    def _restagrup_gated(self, trigger, method):
        """Ejecuta `method` si todo está en orden. Si no: avisa y consulta, o impide continuar si alguna
        comprobación fallida está en modo «impedir»."""
        self.ensure_one()
        if self.env.context.get('restagrup_skip_firewall'):
            return getattr(self, method)()
        issues = self._restagrup_firewall_issues(trigger)
        if not issues:
            return getattr(self, method)()
        text = '\n'.join('• %s' % issue['message'] for issue in issues)
        if any(issue['check'].mode == 'block' for issue in issues):
            raise UserError(_('No se puede continuar todavía:\n%s', text))
        wizard = self.env['restagrup.firewall.wizard'].create({
            'res_model': self._name, 'res_id': self.id, 'method': method, 'message': text,
        })
        return {
            'type': 'ir.actions.act_window', 'name': _('Antes de continuar'), 'res_model': wizard._name,
            'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
        }


class FirewallWizard(models.TransientModel):
    _name = 'restagrup.firewall.wizard'
    _description = 'Aviso del cortafuegos'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    method = fields.Char(required=True)
    message = fields.Text(string='Falta o no cuadra', readonly=True)

    def action_continue(self):
        """Sigue pese a los avisos. Queda anotado quién lo decidió y qué se saltó."""
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        record.message_post(body=Markup('%s<br/>%s') % (
            _('%s continúa pese a los avisos:', self.env.user.name),
            Markup('<br/>').join(Markup.escape(line) for line in self.message.splitlines())))
        result = getattr(record.with_context(restagrup_skip_firewall=True), self.method)()
        return result or {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
