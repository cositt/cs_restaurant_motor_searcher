# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from odoo.addons.restagrup_agency_proposal.controllers.portal import ClientComparisonPortal


class ClientComparisonPortalAlerts(ClientComparisonPortal):

    @http.route()
    def choose(self, search_id, token, line_id=None, **kw):
        search = request.env['restagrup.restaurant.search'].sudo().browse(search_id).exists()
        had_choice = bool(search.chosen_line_id)
        response = super().choose(search_id, token, line_id=line_id, **kw)
        if search and not had_choice and search.chosen_line_id:
            search._restagrup_mark_client_choice()
        return response
