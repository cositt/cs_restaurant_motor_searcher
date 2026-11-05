# -*- coding: utf-8 -*-
"""Página pública de la propuesta conjunta: todos los servicios del grupo y, en cada uno, la agencia elige un
restaurante. El acceso lo da el token del enlace del correo."""
import hmac

from markupsafe import Markup

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
    def choose(self, lead_id, token, search_id=None, line_id=None, **kw):
        lead = self._get_lead(lead_id, token)
        search = lead.restagrup_restaurant_search_ids.filtered(lambda s: str(s.id) == str(search_id))
        if search and not search.chosen_line_id:
            line = next((row['line'] for row in search.restagrup_comparison_rows()
                         if str(row['line'].id) == str(line_id)), None)
            if line:
                line._choose_line()
                lead.message_post(
                    body=Markup('%s') % _('La agencia ha elegido «%(name)s» para %(service)s desde el enlace de la '
                                          'propuesta.', name=line.name, service=lead._restagrup_service_label(search)),
                    message_type='notification', subtype_xmlid='mail.mt_note',
                )
        return request.redirect('/propuesta/%s/%s' % (lead.id, token))
