# -*- coding: utf-8 -*-
"""Ronda 20/11 (2b): editar el menú elegido por la agencia cuando hay cambios posteriores (el postre por teléfono,
un plato que se cambia…). Sale de «Editar menú elegido» en la pestaña Propuesta."""
from markupsafe import Markup

from odoo import Command, _, fields, models
from odoo.exceptions import UserError

from .lead_portal_choice import BULLET, CHOOSABLE_COURSES


class RestaurantSearchLineEditChosenMenu(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def action_edit_chosen_menu(self):
        self.ensure_one()
        wizard = self.env['restagrup.chosen.menu.wizard']._create_for(self)
        return {
            'type': 'ir.actions.act_window', 'name': _('Menú elegido: %s') % self.name,
            'res_model': wizard._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
        }


class ChosenMenuWizard(models.TransientModel):
    _name = 'restagrup.chosen.menu.wizard'
    _description = 'Editar el menú elegido'

    line_id = fields.Many2one('restagrup.restaurant.search.line', required=True, ondelete='cascade')
    menu_id = fields.Many2one(related='line_id.menu_id')
    order_id = fields.Many2one(related='line_id.restagrup_search_order_id')
    line_ids = fields.One2many('restagrup.chosen.menu.wizard.line', 'wizard_id', string='Platos del menú')
    extra_text = fields.Text(
        string='Otros platos o cambios', help='Lo que no está en el menú (alergias, platos pedidos aparte…). Uno por línea.')

    def _create_for(self, line):
        menu_dishes = line.menu_id.line_ids.filtered(lambda dish: dish.course in CHOOSABLE_COURSES)
        names = menu_dishes.mapped('name')
        chosen, extras = set(), []
        for raw in (line.agency_choice_notes or '').replace('\r', '\n').split('\n'):
            written = BULLET.sub('', raw, count=1).strip()
            if not written:
                continue
            dish = line._restagrup_match_dish(written, names) if names else None
            if dish:
                chosen.add(dish)
            else:
                extras.append(written)
        return self.create({
            'line_id': line.id,
            'extra_text': '\n'.join(extras),
            'line_ids': [Command.create({'name': dish.name, 'course': dish.course, 'selected': dish.name in chosen})
                         for dish in menu_dishes],
        })

    def action_save(self):
        self.ensure_one()
        line = self.line_id
        wanted = self.line_ids.filtered('selected').mapped('name')
        extras = [BULLET.sub('', raw, count=1).strip() for raw in (self.extra_text or '').replace('\r', '\n').split('\n')]
        new_notes = '\n'.join('- %s' % item for item in wanted + [extra for extra in extras if extra])
        if not new_notes and not (line.agency_choice_notes or '').strip():
            raise UserError(_('No has elegido ningún plato.'))
        lead = line.search_id.lead_id
        if new_notes != (line.agency_choice_notes or '').strip():
            line.agency_choice_notes = new_notes
            body = Markup('%s<br/>%s') % (
                _('Menú elegido de «%(restaurant)s» editado por %(user)s:', restaurant=line.name, user=self.env.user.name),
                Markup('<br/>').join(Markup.escape(row) for row in new_notes.split('\n')) if new_notes else _('(vacío)'))
            if line.restagrup_search_order_id:
                body += Markup('<br/><i>%s</i>') % _('Si ya enviaste la confirmación o el bono, vuelve a enviarlos.')
            lead.message_post(body=body, subtype_xmlid='mail.mt_note')
        missing = line._restagrup_missing_courses_text()
        if missing:
            lead.message_post(body=missing, subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}


class ChosenMenuWizardLine(models.TransientModel):
    _name = 'restagrup.chosen.menu.wizard.line'
    _description = 'Plato del menú elegido'
    _order = 'id'

    wizard_id = fields.Many2one('restagrup.chosen.menu.wizard', required=True, ondelete='cascade')
    course = fields.Selection(
        selection=lambda self: self.env['restagrup.restaurant.menu.line']._fields['course'].selection, string='Tipo')
    name = fields.Char(string='Plato', readonly=True)
    selected = fields.Boolean(string='Elegido')
