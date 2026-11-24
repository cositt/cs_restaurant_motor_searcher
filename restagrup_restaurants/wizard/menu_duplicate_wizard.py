# -*- coding: utf-8 -*-
"""Reunión 23/11: al leer una respuesta con IA, si la ficha del restaurante ya tiene un menú igual o casi igual, se
avisa antes de crear otro y la persona elige: usar el que hay o crear uno nuevo."""
import json

from odoo import _, api, fields, models


class MenuDuplicateWizard(models.TransientModel):
    _name = 'restagrup.menu.duplicate.wizard'
    _description = 'Aviso: ya hay un menú parecido'

    line_id = fields.Many2one('restagrup.restaurant.search.line', required=True, ondelete='cascade')
    payload = fields.Text(help='Los menús que ha leído la IA, tal cual.')
    summary = fields.Text(compute='_compute_summary')
    can_create_new = fields.Boolean(compute='_compute_summary')

    def _menus(self):
        self.ensure_one()
        try:
            data = json.loads(self.payload or '[]')
        except ValueError:
            data = []
        return [m for m in data if isinstance(m, dict)]

    @api.model
    def _open_for(self, line, menus):
        wizard = self.create({'line_id': line.id, 'payload': json.dumps(menus, ensure_ascii=False)})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ya hay un menú parecido'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.depends('payload', 'line_id')
    def _compute_summary(self):
        for wizard in self:
            menus = wizard._menus()
            fmt = wizard.env['restagrup.pricing'].format_amount
            blocks, all_identical = [], True
            for index, menu, identical in wizard.line_id._restagrup_menu_matches(menus):
                data = menus[index]
                all_identical = all_identical and identical
                incoming = wizard.line_id._restagrup_data_dishes(data)
                existing = {line.name for line in menu.line_ids}
                symbol = menu.currency_id.symbol or ''
                title = _('«%(menu)s» ya está en la ficha: %(price)s %(symbol)s por persona.') % {
                    'menu': menu.name, 'price': fmt(menu.cost_price), 'symbol': symbol}
                if identical:
                    blocks.append(title + '\n' + _('El de la respuesta es idéntico (mismo nombre, precio y platos).'))
                    continue
                lines = [title, _('En la respuesta: «%(name)s», %(price)s %(symbol)s por persona.') % {
                    'name': data.get('nombre') or _('Menú grupos'),
                    'price': fmt(float(data.get('precio_persona') or 0.0)), 'symbol': symbol}]
                new_dishes = sorted(d['nombre'].strip() for d in (data.get('platos') or [])
                                    if isinstance(d, dict) and (d.get('nombre') or '').strip()
                                    and wizard.line_id._normalized_dish(d['nombre']) not in
                                    {wizard.line_id._normalized_dish(n) for n in existing})
                missing = sorted(n for n in existing if wizard.line_id._normalized_dish(n) not in incoming)
                if new_dishes:
                    lines.append(_('Platos nuevos: %s.') % ', '.join(new_dishes))
                if missing:
                    lines.append(_('Platos que ya no vienen: %s.') % ', '.join(missing))
                blocks.append('\n'.join(lines))
            wizard.summary = '\n\n'.join(blocks)
            wizard.can_create_new = not all_identical

    def action_use_existing(self):
        self.ensure_one()
        menus = self._menus()
        reuse = {index: menu for index, menu, _identical in self.line_id._restagrup_menu_matches(menus)}
        self.line_id._restagrup_menus_from_reply(menus, reuse=reuse)
        return self.line_id.action_open_quote_form()

    def action_create_new(self):
        self.ensure_one()
        self.line_id._restagrup_menus_from_reply(self._menus())
        return self.line_id.action_open_quote_form()

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
