# -*- coding: utf-8 -*-
"""Soporte de la pantalla "Guía de la demo": estado de cada paso y simulación del correo de la agencia y de
la respuesta del restaurante, entregándolos por la misma pasarela de correo que usa un buzón real
(`mail.thread.message_process`), sin servidor IMAP/SMTP."""
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from odoo import SUPERUSER_ID, _, api, models
from odoo.exceptions import UserError

AGENCY_FROM = 'Eleanor Whitfield <eleanor@sunriseheritage.demo>'
AGENCY_EMAIL = 'eleanor@sunriseheritage.demo'
RESTAURANT_NAME = 'Asador Sierra Blanca'
PRICE_PER_PERSON = 32

AGENCY_SUBJECT = 'Solicitud de comida para grupo - 32 pax - Málaga 13 nov 2026'
AGENCY_BODY = """Estimado equipo de Restagrup:

Me llamo Eleanor Whitfield y soy responsable de operaciones en Sunrise Heritage Tours (Mánchester, Reino Unido).
Organizamos un viaje cultural a la Costa del Sol y necesitamos una comida de grupo.

Fecha: viernes 13 de noviembre de 2026, a las 14:00.
Lugar: centro de Málaga.
Grupo: 32 personas (30 viajeros y 2 guías), edad media superior a 60 años; evitar escaleras.
Dietas: 3 vegetarianos, 2 celíacos y 1 persona con alergia grave a los frutos secos.
Presupuesto: entre 28 y 35 euros por persona, bebidas incluidas (agua, vino de la casa, refrescos y café).
Nos gustaría un menú de tapas con platos locales.

¿Podrían enviarnos un presupuesto? Necesitamos confirmarlo antes del 30 de octubre.

Un cordial saludo,

Eleanor Whitfield
Responsable de operaciones
Sunrise Heritage Tours Ltd. · +44 161 555 0142
"""


class RestagrupDemoGuide(models.AbstractModel):
    _name = 'restagrup.demo.guide'
    _description = 'Guía de la demo'

    # --- estado de los pasos ---------------------------------------------------------------------------------

    @api.model
    def _lead(self):
        return self.env['crm.lead'].sudo().search([('email_from', 'ilike', AGENCY_EMAIL)], order='id desc', limit=1)

    @api.model
    def _restaurant_line(self, search):
        return search.line_ids.filtered(lambda line: line.name == RESTAURANT_NAME)[:1]

    @api.model
    def get_state(self):
        """Qué paso está hecho y los ids a los que enlazar. Se vuelve a calcular cada vez que se abre la guía."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else self.env['restagrup.restaurant.search']
        line = self._restaurant_line(search) if search else self.env['restagrup.restaurant.search.line']
        order = search.sale_order_id.sudo() if search else self.env['sale.order']
        sheets = order.restaurant_po_ids.sudo() if order else self.env['purchase.order']
        chosen = search.chosen_line_id if search else False
        done = {
            'email': bool(lead),
            'ai': bool(lead) and lead.restagrup_extraction_state == 'done',
            'search': bool(search),
            'request': bool(line) and bool(line.quote_requested_date),
            'reply': bool(line) and line.quote_amount > 0,
            'chosen': bool(chosen) and chosen.etiqueta == 'presupuesto_recibido',
            'order': bool(order),
            'signed': bool(order) and order.state == 'sale',
            'sheet': bool(sheets),
        }
        return {
            'done': done,
            'lead_id': lead.id or False,
            'search_id': search.id or False,
            'order_id': order.id or False,
            'sheet_id': sheets[:1].id or False,
            'portal_url': order.get_portal_url() if order else False,
        }

    # --- simulación de correo entrante -----------------------------------------------------------------------

    @api.model
    def _deliver(self, model, raw_message):
        # Como la pasarela real: la procesa el sistema (OdooBot), no quien pulsa el botón.
        self.env['mail.thread'].with_user(SUPERUSER_ID).message_process(model, raw_message.as_bytes(), save_original=False)

    @api.model
    def simulate_agency_email(self):
        """La agencia manda su petición: entra por la pasarela de correo igual que desde un buzón."""
        if self._lead():
            return self._lead().id
        msg = EmailMessage()
        msg['From'] = AGENCY_FROM
        msg['To'] = 'peticiones@restagrup.local'
        msg['Subject'] = AGENCY_SUBJECT
        msg['Date'] = formatdate(localtime=False)
        msg['Message-Id'] = make_msgid(domain='sunriseheritage.demo')
        msg.set_content(AGENCY_BODY)
        self._deliver('crm.lead', msg)
        return self._lead().id

    @api.model
    def simulate_restaurant_reply(self):
        """El restaurante contesta, en el mismo hilo que la petición de presupuesto que mandó Odoo."""
        lead = self._lead()
        search = lead.restagrup_restaurant_search_ids.sudo()[:1] if lead else False
        line = self._restaurant_line(search) if search else False
        request = line.message_ids.filtered(lambda m: m.message_type == 'email')[:1] if line else False
        if not request:
            raise UserError(_('Primero pide presupuesto al %s desde la búsqueda de restaurantes.') % RESTAURANT_NAME)
        if line.quote_amount:
            return line.id
        pax = search.min_capacity or 32
        total = PRICE_PER_PERSON * pax
        msg = EmailMessage()
        msg['From'] = '%s <%s>' % (line.name, line.email or 'reservas@asadorsierrablanca.demo')
        msg['To'] = 'respuestas@restagrup.local'
        msg['Subject'] = 'Re: %s' % (request.subject or AGENCY_SUBJECT)
        msg['Date'] = formatdate(localtime=False)
        msg['Message-Id'] = make_msgid(domain='asadorsierrablanca.demo')
        msg['In-Reply-To'] = request.message_id
        msg['References'] = request.message_id
        msg.set_content(
            'Hola,\n\nGracias por contactar con nosotros. Sí, tenemos disponibilidad para recibir a vuestro grupo de '
            '%(pax)d personas y estaremos encantados de atenderos.\n\nOs proponemos un menú de grupo: entrantes para '
            'compartir, un principal a elegir entre pescado o carne, postre casero y café. Bebidas incluidas (agua, '
            'vino de la casa y refrescos).\n\nPrecio: %(price)d euros por persona (IVA no incluido), es decir, '
            '%(total)d euros en total para el grupo. Podemos adaptar el menú para vegetarianos, celíacos y alergias a '
            'frutos secos. El local es accesible y no tiene escaleras.\n\nUn saludo,\n%(name)s\nReservas de grupos\n' % {
                'pax': pax, 'price': PRICE_PER_PERSON, 'total': total, 'name': line.name})
        self._deliver('restagrup.restaurant.search.line', msg)
        return line.id

    # --- reinicio ------------------------------------------------------------------------------------------------

    @api.model
    def reset_demo(self):
        """Deja la demo como nueva. Solo en la BD de demo (parámetro restagrup_demo.enabled = 1)."""
        if self.env['ir.config_parameter'].sudo().get_param('restagrup_demo.enabled') != '1':
            raise UserError(_('El reinicio solo está disponible en la base de datos de demo.'))
        env = self.env
        sheets = env['purchase.order'].sudo().with_context(active_test=False).search([])
        sheets.filtered(lambda po: po.state != 'cancel').button_cancel()
        sheets.unlink()
        orders = env['sale.order'].sudo().with_context(active_test=False).search([])
        orders.filtered(lambda so: so.state != 'cancel')._action_cancel()
        orders.unlink()
        env['restagrup.pending.mail'].sudo().search([]).unlink()
        env['restagrup.restaurant.notice'].sudo().search([]).unlink()
        env['restagrup.restaurant.search'].sudo().search([]).unlink()
        env['crm.lead'].sudo().with_context(active_test=False).search([]).unlink()
        env['res.partner'].sudo().search([('email', 'ilike', AGENCY_EMAIL), ('is_restaurant', '=', False)]).unlink()
        return True
