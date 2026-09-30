# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class MenuSelectionWizard(models.TransientModel):
    _name = 'restagrup.menu.selection.wizard'
    _description = 'Elegir menús del restaurante para el presupuesto de venta'

    search_id = fields.Many2one('restagrup.restaurant.search', required=True, ondelete='cascade')
    restaurant_id = fields.Many2one(
        'res.partner', string='Restaurante', related='search_id.chosen_line_id.partner_id',
    )
    line_ids = fields.One2many('restagrup.menu.selection.wizard.line', 'wizard_id', string='Menús')

    def action_confirm(self):
        self.ensure_one()
        chosen = self.line_ids.filtered('selected')
        if not chosen:
            raise UserError(_('Marca al menos un menú para el presupuesto.'))
        if any(line.quantity <= 0 for line in chosen):
            raise UserError(_('La cantidad de cada menú marcado debe ser mayor que cero.'))
        selection = [(line.product_tmpl_id.product_variant_id, line.quantity) for line in chosen]
        self.search_id._create_sale_order_from_menus(selection)
        return self.search_id._action_view_sale_order()


class MenuSelectionWizardLine(models.TransientModel):
    _name = 'restagrup.menu.selection.wizard.line'
    _description = 'Línea del asistente de menús'

    wizard_id = fields.Many2one('restagrup.menu.selection.wizard', required=True, ondelete='cascade')
    product_tmpl_id = fields.Many2one('product.template', string='Menú', required=True)
    restaurant_price = fields.Float(related='product_tmpl_id.standard_price', string='Precio del restaurante (€)')
    client_price = fields.Float(related='product_tmpl_id.restagrup_client_price', string='Precio al cliente (€)')
    selected = fields.Boolean(string='Incluir', default=False)
    quantity = fields.Float(string='Cantidad', default=1.0)
