# -*- coding: utf-8 -*-
"""Soporte de la pantalla «Guía de la demo 2»: estado de cada paso y simulación de los correos de la agencia y de los
restaurantes, entregados por la misma pasarela que un buzón real (`mail.thread.message_process`), sin IMAP/SMTP."""
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from odoo import SUPERUSER_ID, _, api, models
from odoo.exceptions import UserError

AGENCY_FROM = 'Lucía Prieto <lucia@costaviajes.demo>'
AGENCY_EMAIL = 'lucia@costaviajes.demo'
AGENCY_SUBJECT = 'Comida para un grupo senior en Sevilla'
AGENCY_BODY = """Hola, buenos días:

Somos Costa Viajes Ibéricos y necesitamos una comida de grupo en Sevilla para 45 personas, un grupo senior (adultos
mayores de 65 años). Aún no tenemos cerrada la fecha, os la confirmo en cuanto la tengamos.

¿Podríais enviarnos opciones de restaurante con menú y precio?

Un saludo,
Lucía Prieto
Costa Viajes Ibéricos
"""
AGENCY_REPLY = """Hola, gracias por escribirnos.

La fecha es el viernes 11 de diciembre de 2026, a las 14:00. No tenemos un presupuesto cerrado: lo que sea
razonable para un grupo de este tipo.

Un saludo,
Lucía Prieto
"""
# Los tres restaurantes a los que se pide presupuesto: nombre -> precio por persona (el de su menú de 2026)
QUOTE_RESTAURANTS = {
    'Taberna del Patio Andaluz': 26.0,
    'Casa Giralda Grupos': 28.0,
    'Bodega San Telmo': 24.5,
}
GRATUITIES = 2


class RestagrupDemo2Guide(models.AbstractModel):
    _name = 'restagrup.demo2.guide'
    _description = 'Guía de la demo 2'

    # --- estado de los pasos ---------------------------------------------------------------------------------

    @api.model
    def _lead(self):
        return self.env['crm.lead'].sudo().with_context(active_test=False).search(
            [('email_from', 'ilike', AGENCY_EMAIL)], order='id desc', limit=1)

    @api.model
    def _quote_lines(self, search):
        return search.line_ids.filtered(lambda line: line.name in QUOTE_RESTAURANTS)

    @api.model
    def get_state(self):
        """Qué paso está hecho y los ids a los que enlazar. Se vuelve a calcular cada vez que se abre la guía."""
        lead = self._lead()
        pending = self.env['restagrup.pending.mail'].sudo().search(
            [('request_lead_id', '=', lead.id)], limit=1) if lead else self.env['restagrup.pending.mail']
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else self.env['restagrup.restaurant.search']
        lines = self._quote_lines(search) if search else self.env['restagrup.restaurant.search.line']
        order = search.sale_order_id.sudo() if search else self.env['sale.order']
        asked = bool(lead) and lead.restagrup_data_request_count >= 1
        done = {
            'email': bool(lead),
            'ask': bool(pending) or asked,
            'approve': asked,
            'reply': asked and not lead._restagrup_missing_request_data(),
            'menus': bool(search),
            'search': bool(search),
            'request': len(lines.filtered('quote_requested_date')) >= len(QUOTE_RESTAURANTS),
            'answers': len(lines.filtered(lambda l: l.quote_amount > 0)) >= len(QUOTE_RESTAURANTS),
            'confirm': len(lines.filtered(lambda l: l.etiqueta == 'presupuesto_recibido')) >= len(QUOTE_RESTAURANTS),
            'proposal': bool(lead) and lead.restagrup_stage_key in ('presupuesto', 'expediente', 'cerrado'),
            'choose': bool(search) and bool(search.chosen_line_id),
            'order': bool(order),
            'sign': bool(order) and order.state == 'sale',
            'docs': bool(order) and any(order.order_line.mapped('restagrup_gratuities')),
            'paid': bool(order) and order.restagrup_paid,
        }
        return {
            'done': done,
            'lead_id': lead.id or False,
            'search_id': search.id or False,
            'order_id': order.id or False,
            'sheet_id': order.restaurant_po_ids[:1].id or False,
            'visible': search.restaurant_visible if search else True,
            'search_portal_url': search._comparison_portal_url() if search and search.comparison_token else False,
            'order_portal_url': order.get_portal_url() if order else False,
        }

    # --- simulación de correo entrante -----------------------------------------------------------------------

    @api.model
    def _message(self, sender, to, subject, body, domain, in_reply_to=False):
        msg = EmailMessage()
        msg['From'] = sender
        msg['To'] = to
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=False)
        msg['Message-Id'] = make_msgid(domain=domain)
        if in_reply_to:
            msg['In-Reply-To'] = in_reply_to
            msg['References'] = in_reply_to
        msg.set_content(body)
        return msg

    @api.model
    def _deliver(self, model, raw_message):
        # Como la pasarela real: la procesa el sistema (OdooBot), no quien pulsa el botón.
        self.env['mail.thread'].with_user(SUPERUSER_ID).message_process(model, raw_message.as_bytes(), save_original=False)

    @api.model
    def simulate_agency_email(self):
        """La agencia manda su petición, incompleta (sin fecha): entra por la pasarela de correo."""
        if self._lead():
            return self._lead().id
        self._deliver('crm.lead', self._message(
            AGENCY_FROM, 'peticiones@restagrup.local', AGENCY_SUBJECT, AGENCY_BODY, 'costaviajes.demo'))
        return self._lead().id

    @api.model
    def simulate_agency_reply(self):
        """La agencia contesta a la petición de datos, en el mismo hilo."""
        lead = self._lead()
        request = lead.message_ids.filtered(
            lambda m: m.message_type == 'email' and (m.subject or '').startswith('Datos que nos faltan'))[:1] if lead else False
        if not request:
            raise UserError(_('Primero aprueba el envío de la petición de datos (menú «Pendientes de aprobar»).'))
        if not lead._restagrup_missing_request_data():
            return lead.id
        self._deliver('crm.lead', self._message(
            AGENCY_FROM, 'peticiones@restagrup.local', 'Re: %s' % request.subject, AGENCY_REPLY,
            'costaviajes.demo', in_reply_to=request.message_id))
        return lead.id

    @api.model
    def request_quotes(self):
        """«Pedir presupuesto» a los tres restaurantes: el clic de quien presenta es la aprobación."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else False
        lines = self._quote_lines(search) if search else False
        if not lines:
            raise UserError(_('Primero busca restaurantes desde la petición («Buscar para todos los eventos»).'))
        for line in lines.filtered(lambda l: not l.quote_requested_date):
            line.action_request_quote()
        return search.id

    @api.model
    def simulate_restaurant_replies(self):
        """Los tres restaurantes contestan en el hilo de su petición, cada uno con su menú y su precio."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else False
        lines = self._quote_lines(search) if search else False
        if not lines or not all(lines.mapped('quote_requested_date')):
            raise UserError(_('Primero pide presupuesto a los tres restaurantes.'))
        pax = search.min_capacity or 45
        for line in lines.filtered(lambda l: not l.quote_amount):
            request = line.message_ids.filtered(lambda m: m.message_type == 'email')[:1]
            price = QUOTE_RESTAURANTS[line.name]
            menu = self.env['restagrup.restaurant.menu'].sudo().search(
                [('partner_id', '=', line.partner_id.id), ('season', '=', 2026)], limit=1)
            body = (
                'Hola,\n\nGracias por contactar con nosotros. Tenemos disponibilidad para vuestro grupo de %(pax)d '
                'personas.\n\nOs proponemos nuestro %(menu)s:\n%(text)s\n\nPrecio: %(price).2f euros por persona (IVA '
                'incluido), es decir, %(total).2f euros en total para el grupo.\n\nUn saludo,\n%(name)s\nReservas de '
                'grupos\n' % {'pax': pax, 'menu': menu.name or 'menú de grupo', 'text': menu.description or '',
                              'price': price, 'total': price * pax, 'name': line.name})
            self._deliver('restagrup.restaurant.search.line', self._message(
                '%s <%s>' % (line.name, line.email or line.partner_id.email), 'respuestas@restagrup.local',
                'Re: %s' % (request.subject or 'Petición de presupuesto'), body, 'restaurante.demo',
                in_reply_to=request.message_id))
            if menu:
                line.menu_id = menu
        return search.id

    @api.model
    def confirm_quotes(self):
        """Una persona confirma los importes que propuso la IA (aquí, con un clic para los tres)."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else False
        lines = self._quote_lines(search) if search else False
        if not lines or not any(lines.mapped('quote_amount')):
            raise UserError(_('Primero tienen que contestar los restaurantes.'))
        for line in lines.filtered(lambda l: l.quote_amount and l.etiqueta != 'presupuesto_recibido'):
            line.action_register_quote()
        return search.id

    @api.model
    def toggle_visible(self):
        """Enseña u oculta el nombre de los restaurantes en la propuesta al cliente."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else False
        if not search:
            raise UserError(_('Primero busca restaurantes.'))
        search.restaurant_visible = not search.restaurant_visible
        return search.restaurant_visible

    @api.model
    def apply_gratuities(self):
        """Dos gratuidades (guía y chófer): no pagan, pero cuentan como comensales en los documentos."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else False
        order = search.sale_order_id.sudo() if search else False
        if not order:
            raise UserError(_('Primero crea el presupuesto de venta.'))
        line = order.order_line.filtered('restaurant_id')[:1]
        if line and not line.restagrup_gratuities:
            line.write({'product_uom_qty': line.product_uom_qty - GRATUITIES, 'restagrup_gratuities': GRATUITIES})
        return order.id

    # --- reinicio ------------------------------------------------------------------------------------------------

    @api.model
    def reset_demo(self):
        """Quita solo lo del recorrido (la agencia Costa Viajes y su petición). Los documentos de ejemplo de las
        listas se quedan. Solo en la BD de la demo 2 (parámetro restagrup_demo2.enabled = 1)."""
        if self.env['ir.config_parameter'].sudo().get_param('restagrup_demo2.enabled') != '1':
            raise UserError(_('El reinicio solo está disponible en la base de datos de la demo 2.'))
        env = self.env
        lead = self._lead()
        searches = lead.restagrup_restaurant_search_ids.sudo() if lead else env['restagrup.restaurant.search']
        orders = (searches.sale_order_id | lead.sudo().order_ids) if lead else env['sale.order']
        sheets = orders.restaurant_po_ids.sudo().with_context(active_test=False)
        sheets.filtered(lambda po: po.state != 'cancel').button_cancel()
        sheets.unlink()
        orders.sudo().filtered(lambda so: so.state != 'cancel')._action_cancel()
        orders.sudo().unlink()
        env['restagrup.pending.mail'].sudo().search([('request_lead_id', '=', lead.id)]).unlink() if lead else None
        env['restagrup.restaurant.notice'].sudo().search([('lead_id', '=', lead.id)]).unlink() if lead else None
        searches.unlink()
        if lead:
            lead.sudo().with_context(active_test=False).unlink()
        env['res.partner'].sudo().search([('email', 'ilike', AGENCY_EMAIL), ('is_restaurant', '=', False)]).unlink()
        return True
