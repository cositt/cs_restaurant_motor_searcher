# -*- coding: utf-8 -*-
"""Completar con la IA los platos de un menú que solo tiene la descripción escrita (como en el CRM de Restagrup).
La descripción no se toca; los platos salen de ella. No pasa a «sin revisar»: es lo que ya escribió una persona,
solo que ordenado. Queda en «Actividad IA» (idea de Juan sobre el PPT de Conchita 2026-11-04, diapositiva 6)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .restaurant_menu import COURSES

COURSE_KEYS = {key for key, _label in COURSES}
DISHES_SYSTEM_PROMPT = """\
Te paso la descripción de un menú de restaurante para grupos, tal como la escribió una persona.
Sepárala en platos. Devuelve SOLO un objeto JSON, sin texto adicional, con la clave "platos": lista de objetos
{"tipo": uno de entrante, principal, postre, bebida, otro; "nombre": el plato tal como está escrito}.
Mantén el orden del texto. No inventes platos que no estén; los títulos de sección (ENTRANTES, POSTRE...) no son
platos. Las bebidas incluidas van como "bebida"."""


class RestaurantMenuDishes(models.Model):
    _inherit = 'restagrup.restaurant.menu'

    dishes_missing = fields.Boolean(
        string='Platos sin completar', compute='_compute_dishes_missing', store=True,
        help='Tiene el menú en la descripción pero ningún plato: «Completar platos con IA» los separa.')

    @api.depends('description', 'line_ids')
    def _compute_dishes_missing(self):
        for menu in self:
            menu.dishes_missing = bool((menu.description or '').strip()) and not menu.line_ids

    def action_complete_dishes_ai(self):
        menus = self.filtered('dishes_missing')
        if not menus:
            raise UserError(_('Ninguno de los menús elegidos tiene platos por completar.'))
        failed = menus.filtered(lambda menu: not menu._restagrup_complete_dishes())
        if failed == menus:
            raise UserError(_('La IA no ha podido separar los platos (sin respuesta). Inténtalo más tarde o '
                              'escríbelos a mano en la pestaña «Platos».'))
        done = len(menus) - len(failed)
        message = _('Platos completados en %s menú(s).') % done
        if failed:
            message += ' ' + _('Sin respuesta de la IA en: %s.') % ', '.join(failed.mapped('name'))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'message': message, 'type': 'warning' if failed else 'success',
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    def _restagrup_complete_dishes(self):
        """Pide los platos a la IA y los guarda. Devuelve False si la IA no contesta."""
        self.ensure_one()
        data, _provider, _log = self.env['restagrup.llm.connector'].run(
            'menu_dishes', DISHES_SYSTEM_PROMPT, self.description, source=self, label=self.name, review=False)
        if not isinstance(data, dict):
            return False
        dishes = [dish for dish in (data.get('platos') or [])
                  if isinstance(dish, dict) and isinstance(dish.get('nombre'), str) and dish['nombre'].strip()]
        self.write({'line_ids': [(0, 0, {
            'course': course if course in COURSE_KEYS else 'otro',
            'name': dish['nombre'].strip(), 'sequence': index,
        }) for index, dish in enumerate(dishes) for course in [str(dish.get('tipo') or '').strip().lower()]]})
        return True
