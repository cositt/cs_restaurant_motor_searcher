# -*- coding: utf-8 -*-
from odoo import api, models

DEFAULT_LANG = 'es_ES'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _restagrup_set_default_lang(self):
        """Los contactos nuevos nacen en español. Sin esto, los que crean el buzón y los crons (OdooBot, en inglés)
        nacen en inglés y los correos estándar de Odoo (presupuesto, pedido) les salen en inglés. Quien quiera otro
        idioma para un contacto lo cambia en su ficha."""
        if not self.env['res.lang']._lang_get(DEFAULT_LANG):
            return
        self.env['ir.default'].set('res.partner', 'lang', DEFAULT_LANG)
