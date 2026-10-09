# -*- coding: utf-8 -*-
import hmac

from markupsafe import Markup

from odoo import _, http
from odoo.http import request

TEMPLATE = 'restagrup_agency_proposal.portal_client_comparison'


class ClientComparisonPortal(http.Controller):
    """Página pública de la comparativa. El acceso lo da el token del enlace, que solo existe si quien envió la
    comparativa pidió incluir el enlace."""

    def _get_search(self, search_id, token):
        search = request.env['restagrup.restaurant.search'].sudo().browse(search_id).exists()
        stored = search.comparison_token if search else False
        if not stored or not hmac.compare_digest(stored.encode(), (token or '').encode()):
            raise request.not_found()
        return search

    def _render(self, search, token, **extra):
        rows = search.restagrup_comparison_rows()
        chosen = search.chosen_line_id
        chosen_label = next((row['name'] for row in rows if row['line'] == chosen), None)
        if chosen and chosen_label is None:
            chosen_label = chosen.name if search.restaurant_visible else _('la opción elegida')
        values = {
            'search': search, 'token': token, 'rows': rows, 'chosen': chosen, 'chosen_label': chosen_label,
            'currency': search.env.company.currency_id,
        }
        values.update(extra)
        return request.render(TEMPLATE, values)

    @http.route('/comparativa/<int:search_id>/<string:token>', type='http', auth='public', methods=['GET'],
                csrf=False, sitemap=False)
    def comparison(self, search_id, token, **kw):
        search = self._get_search(search_id, token)
        return self._render(search, token)

    @http.route('/comparativa/<int:search_id>/<string:token>/elegir', type='http', auth='public',
                methods=['POST'], csrf=False, sitemap=False)
    def choose(self, search_id, token, line_id=None, **kw):
        search = self._get_search(search_id, token)
        if not search.chosen_line_id:
            line = next((row['line'] for row in search.restagrup_comparison_rows()
                         if str(row['line'].id) == str(line_id)), None)
            if line:
                line._choose_line()
                search.lead_id.message_post(
                    body=Markup('%s') % _('El cliente ha elegido «%s» desde el portal de la comparativa.', line.name),
                    message_type='notification', subtype_xmlid='mail.mt_note',
                )
        return request.redirect('/comparativa/%s/%s' % (search.id, token))
