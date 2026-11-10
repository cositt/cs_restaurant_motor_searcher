# -*- coding: utf-8 -*-
"""Presupuesto con el precio del catálogo, sin esperar al restaurante (ronda de ajustes 09/11).

Muchas veces ya se sabe lo que cobra el restaurante (su menú está en la ficha) y no hace falta esperar a que
conteste para dar el presupuesto a la agencia. Se usa el coste del menú como presupuesto y queda marcado
«disponibilidad sin confirmar» hasta que el restaurante la confirme."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RestaurantSearchLineCatalogQuote(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    quote_availability_pending = fields.Boolean(
        string='Disponibilidad sin confirmar', copy=False,
        help='El presupuesto sale del precio del menú en el catálogo: el restaurante aún no ha confirmado que'
             ' tenga sitio para el grupo ese día.')
    partner_menu_count = fields.Integer(related='partner_id.restaurant_menu_count', string='Menús en su ficha')

    def _catalog_menus(self):
        self.ensure_one()
        return self.partner_id.restaurant_menu_ids.filtered('active')

    def action_quote_from_catalog(self):
        """Presupuesto con el menú de su ficha. Con un solo menú se registra directamente; con varios se abre el
        formulario para elegir cuál (el precio se rellena al elegirlo)."""
        self.ensure_one()
        menus = self._catalog_menus()
        if not menus:
            raise UserError(_('%s no tiene menús en su ficha: añádelos o pídele presupuesto.') % self.name)
        menu = self.menu_id if self.menu_id in menus else (menus if len(menus) == 1 else False)
        if not menu:
            action = self.action_open_quote_form()
            action['name'] = _('Presupuesto con precio de catálogo')
            action['context'] = dict(action.get('context') or {}, restagrup_from_catalog=True)
            return action
        self._apply_catalog_quote(menu)
        return True

    def _apply_catalog_quote(self, menu):
        self.write({
            'menu_id': menu.id,
            'quote_price_pp': menu.cost_price_eur,
            'etiqueta': 'presupuesto_recibido',
            'quote_received_date': self.quote_received_date or fields.Datetime.now(),
            'quote_availability_pending': True,
        })
        self.search_id.message_post_if_exists(_(
            '%(name)s: presupuesto con el precio del catálogo (%(menu)s, %(price)s) — disponibilidad sin'
            ' confirmar.') % {'name': self.name, 'menu': menu.name, 'price': self._quote_price_text()})

    @api.onchange('menu_id')
    def _onchange_menu_catalog_price(self):
        """Al elegir un menú del catálogo sin precio escrito, se rellena con el coste del menú."""
        for line in self:
            if line.menu_id and not line.quote_price_pp:
                line.quote_price_pp = line.menu_id.cost_price_eur

    def action_register_quote(self):
        if self.env.context.get('restagrup_from_catalog'):
            self.ensure_one()
            if not self.menu_id:
                raise UserError(_('Elige el menú del catálogo.'))
            self._apply_catalog_quote(self.menu_id)
            if self.env.context.get('choose_after_register'):
                self._choose_line()
            return {'type': 'ir.actions.act_window_close'}
        result = super().action_register_quote()
        # Un presupuesto dado por el propio restaurante (correo, WhatsApp, teléfono) ya confirma que tiene sitio.
        self.quote_availability_pending = False
        return result

    def action_confirm_availability(self):
        for line in self:
            line.quote_availability_pending = False
            line.search_id.message_post_if_exists(_('%s: disponibilidad confirmada.') % line.name)
        return True

    def action_preview_menu(self):
        """El «ojo» de la propuesta: los platos del menú de este presupuesto sin salir de la pestaña."""
        self.ensure_one()
        if not self.menu_id:
            raise UserError(_('%s no tiene menú asignado en este presupuesto.') % self.name)
        return self.menu_id.action_preview_dishes()
