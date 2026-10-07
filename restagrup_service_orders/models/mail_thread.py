# -*- coding: utf-8 -*-
import re

from odoo import api, models
from odoo.tools import html2plaintext

ORDER_REFERENCE = re.compile(r'\bS\d{4,}\b', re.IGNORECASE)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def _restagrup_match_existing(self, category, message_dict):
        """A5: si el correo cita un presupuesto (p. ej. S00012) que existe, va a su hilo."""
        text = '%s %s' % (message_dict.get('subject') or '', html2plaintext(message_dict.get('body') or ''))
        names = {ref.upper() for ref in ORDER_REFERENCE.findall(text)}
        if names:
            orders = self.env['sale.order'].sudo().search([('name', 'in', list(names))])
            if len(orders) == 1:
                return 'sale.order', orders.id
        return super()._restagrup_match_existing(category, message_dict)
