# -*- coding: utf-8 -*-
"""Página pública de la propuesta conjunta: todos los servicios del grupo y, en cada uno, la agencia elige un
restaurante. El acceso lo da el token del enlace del correo."""
import hmac

from odoo import _, http
from odoo.http import request

TEMPLATE = 'restagrup_agency_proposal.portal_lead_proposal'


class LeadProposalPortal(http.Controller):

    def _get_lead(self, lead_id, token):
        lead = request.env['crm.lead'].sudo().browse(lead_id).exists()
        stored = lead.restagrup_proposal_token if lead else False
        if not stored or not hmac.compare_digest(stored.encode(), (token or '').encode()):
            raise request.not_found()
        return lead

    @http.route('/propuesta/<int:lead_id>/<string:token>', type='http', auth='public', methods=['GET'],
                csrf=False, sitemap=False)
    def proposal(self, lead_id, token, **kw):
        lead = self._get_lead(lead_id, token)
        sections = []
        for section in lead._restagrup_proposal_sections():
            search = section['search']
            chosen = search.chosen_line_id
            label = next((row['name'] for row in section['rows'] if row['line'] == chosen), None)
            if chosen and label is None:
                label = chosen.name if search.restaurant_visible else _('la opción elegida')
            sections.append(dict(section, chosen=chosen, chosen_label=label))
        return request.render(TEMPLATE, {
            'lead': lead, 'token': token, 'sections': sections, 'currency': lead.env.company.currency_id,
        })

    @http.route('/propuesta/<int:lead_id>/<string:token>/elegir', type='http', auth='public', methods=['POST'],
                csrf=False, sitemap=False)
    def choose(self, lead_id, token, search_id=None, line_id=None, dishes=None, **kw):
        lead = self._get_lead(lead_id, token)
        lead._restagrup_portal_choose(search_id, line_id, dishes)
        return request.redirect('/propuesta/%s/%s' % (lead.id, token))
