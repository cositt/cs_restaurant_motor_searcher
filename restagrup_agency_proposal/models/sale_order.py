# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def restagrup_proposal_groups(self):
        """Líneas incluidas en la propuesta, agrupadas por restaurante y
        ordenadas por nombre -- usado por el report QWeb de propuesta."""
        self.ensure_one()
        grouped = defaultdict(lambda: self.env['sale.order.line'])
        for line in self.order_line:
            if line.restaurant_id and not line.display_type and line.restagrup_include_in_proposal:
                grouped[line.restaurant_id] |= line
        return sorted(grouped.items(), key=lambda item: item[0].name or '')
