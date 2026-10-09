# -*- coding: utf-8 -*-
import json

from markupsafe import Markup

from odoo import _, fields, models
from odoo.tools import email_normalize, html2plaintext

MAX_DATA_REQUESTS = 2  # a la tercera, una persona

COMPLETION_SYSTEM_PROMPT = """\
Eres un asistente que lee la respuesta de una agencia a una petición de datos que faltaban de un grupo.
Hoy es {hoy}. Recibirás los datos que se pidieron, los servicios del grupo con su id y la respuesta.
Devuelve SOLO un objeto JSON, sin texto adicional, con la clave "eventos": una lista con un objeto por cada
servicio sobre el que la respuesta aporte datos, con las claves "id" (el de la lista, nunca otro),
"ciudad" (string o null), "fecha" (YYYY-MM-DD o null; si no indica el año, la próxima vez que ocurra
a partir de hoy) y "pax" (entero o null). Si el grupo no tiene servicios en la lista, devuelve también las
claves sueltas "ciudad", "fecha" y "pax". Si un dato no aparece claramente, pon null: nunca lo inventes."""


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_restaurant_search_ids = fields.One2many(
        'restagrup.restaurant.search', 'lead_id', string='Búsquedas de restaurantes',
    )
    restagrup_restaurant_search_count = fields.Integer(
        string='Nº búsquedas', compute='_compute_restagrup_restaurant_search_count',
    )

    restagrup_data_request_count = fields.Integer(
        string='Peticiones de datos enviadas', default=0, copy=False,
        help='Cuántas veces se ha pedido a la agencia lo que faltaba de la petición. Tras dos, la mira una persona.',
    )

    def _compute_restagrup_restaurant_search_count(self):
        for lead in self:
            lead.restagrup_restaurant_search_count = len(lead.restagrup_restaurant_search_ids)

    # --- pedir a la agencia lo que falta ---

    def _restagrup_after_extraction(self, log):
        """Completa: no interviene nadie. Incompleta: se pide a la agencia solo lo que falta, y solo si no se
        puede (sin email, o ya se pidió dos veces) la mira una persona."""
        self.ensure_one()
        missing = self._restagrup_missing_request_data()
        if missing and self._restagrup_can_ask():
            self._restagrup_ask_for_missing_data()
            self._restagrup_announce(_('Grupo nuevo con datos por completar: %s') % self.name,
                                     _('Se pedirá a la agencia: %s') % '; '.join(missing))
            return
        super()._restagrup_after_extraction(log)

    def _restagrup_sender_email(self):
        return email_normalize(self.email_from or '') or False

    def _restagrup_can_ask(self):
        return bool(self._restagrup_sender_email()) and self.restagrup_data_request_count < MAX_DATA_REQUESTS

    def _restagrup_data_request_content(self, missing, signer):
        subject = _('Datos que nos faltan de vuestra petición — %s') % (self.name or '')
        lines = [_('Hola,'), '', _('Para poder buscar restaurante nos faltan estos datos de vuestra petición:'), '']
        lines += ['- %s' % item for item in missing] + ['', _('Gracias,'), signer]
        return subject, '\n'.join(lines)

    def _restagrup_ask_for_missing_data(self):
        """Pide a la agencia lo que falta. Con envíos «con aprobación» (por defecto) el correo espera en la cola;
        en automático sale ya."""
        self.ensure_one()
        missing = self._restagrup_missing_request_data()
        email_to = self._restagrup_sender_email()
        if not missing or not email_to or self.restagrup_data_request_count >= MAX_DATA_REQUESTS:
            return False
        subject, body = self._restagrup_data_request_content(missing, self.user_id.name or self.env.company.name)
        queue = self.env['restagrup.pending.mail']
        if queue._send_mode() == 'automatic':
            self._restagrup_send_data_request(subject, body, email_to)
        else:
            queue._enqueue_lead_data_request(self, email_to, subject, body, missing)
        return True

    def _restagrup_send_data_request(self, subject, body_text, email_to):
        """Envía la petición por el hilo del lead: la respuesta de la agencia vuelve a este mismo lead."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject,
            message_type='email',
            subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(self.user_id.email or self.env.user.email),
            outgoing_email_to=email_to,
        )
        self.restagrup_data_request_count += 1

    # --- leer la respuesta ---

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for lead in self:
            lead._restagrup_complete_from_reply(msg_dict)
        return res

    def _restagrup_complete_from_reply(self, msg_dict):
        """La respuesta de la agencia a una petición de datos rellena los huecos del lead, sin pisar nada que ya
        tenga. Si queda algo por aclarar se vuelve a preguntar (hasta dos veces); después, una persona."""
        self.ensure_one()
        if not self.restagrup_data_request_count:
            return
        missing = self._restagrup_missing_request_data()
        if not missing:
            return
        raw_body = msg_dict.get('body') or ''
        text = html2plaintext(raw_body).strip() if raw_body else ''
        if not text:
            return
        events = [{'id': e.id, 'ciudad': e.city, 'fecha': e.event_date and e.event_date.isoformat(), 'pax': e.pax}
                  for e in self.restagrup_event_ids]
        content = 'PEDIDO:\n%s\n\nSERVICIOS:\n%s\n\nRESPUESTA:\n%s' % (
            '\n'.join(missing), json.dumps(events, ensure_ascii=False), text)
        prompt = COMPLETION_SYSTEM_PROMPT.replace('{hoy}', fields.Date.context_today(self).isoformat())
        data, _provider, _log = self.env['restagrup.llm.connector'].run(
            'lead_completion', prompt, content[:4000], source=self, label=self.name, review=False)
        if data is None:  # la IA falló (ya avisó): no se insiste a la agencia, lo mira una persona
            self._restagrup_hand_over(missing)
            return
        self._restagrup_apply_reply(data)
        missing = self._restagrup_missing_request_data()
        if not missing:
            self._restagrup_announce(_('La agencia ha completado los datos: %s') % self.name)
        elif self._restagrup_can_ask():
            self._restagrup_ask_for_missing_data()
        else:
            self._restagrup_hand_over(missing)

    def _restagrup_apply_reply(self, data):
        """Rellena solo lo vacío: lo que el lead ya tenía no se toca, y solo se aceptan ids de sus servicios."""
        own = {event.id: event for event in self.restagrup_event_ids}
        for item in data.get('eventos') or []:
            event = own.get(item.get('id')) if isinstance(item, dict) else None
            if not event:
                continue
            vals = {}
            if not event.city and isinstance(item.get('ciudad'), str) and item['ciudad'].strip():
                vals['city'] = item['ciudad'].strip()
            if not event.event_date and self._restagrup_safe_date(item.get('fecha')):
                vals['event_date'] = self._restagrup_safe_date(item['fecha'])
            if not event.pax and self._restagrup_safe_int(item.get('pax')) > 0:
                vals['pax'] = self._restagrup_safe_int(item['pax'])
            if vals:
                event.write(vals)
        if not own:  # sin servicios: valen los datos sueltos
            vals = {}
            if not self.restagrup_city and isinstance(data.get('ciudad'), str) and data['ciudad'].strip():
                vals['restagrup_city'] = data['ciudad'].strip()
            if not self.restagrup_service_date and self._restagrup_safe_date(data.get('fecha')):
                vals['restagrup_service_date'] = self._restagrup_safe_date(data['fecha'])
            if not self.restagrup_pax and self._restagrup_safe_int(data.get('pax')) > 0:
                vals['restagrup_pax'] = self._restagrup_safe_int(data['pax'])
            if vals:
                self.write(vals)

    def _restagrup_review_extraction(self):
        """Empezar a buscar restaurantes es la revisión humana de la extracción de la IA: se confirma si los
        datos del lead siguen como los propuso, y se marca como corregida si alguien los cambió."""
        for lead in self:
            log = self.env['restagrup.ai.log']._pending('lead_extraction', lead)
            if not log:
                continue
            data = json.loads(log.output or '{}')
            first = (lead._restagrup_event_vals_list(data) or [{}])[0]
            city = (data.get('ciudad') or first.get('city') or '') or False
            pax = lead._restagrup_safe_int(data.get('num_pax') or first.get('pax'))
            same = (lead.restagrup_city or False) == city and lead.restagrup_pax == pax
            log._close('confirmed' if same else 'corrected')

    def action_view_restaurant_searches(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Búsquedas de restaurantes',
            'res_model': 'restagrup.restaurant.search',
            'domain': [('lead_id', '=', self.id)],
            'context': {
                'default_lead_id': self.id,
                'default_city': self.restagrup_city,
                'default_min_capacity': self.restagrup_pax,
            },
        }
        if self.restagrup_restaurant_search_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.restagrup_restaurant_search_ids.id,
            })
        else:
            action['view_mode'] = 'list,form'
        return action

    def action_search_all_events(self):
        """Una búsqueda por cada evento en borrador que ya tenga ciudad; los que ya tienen búsqueda
        no se duplican."""
        self.ensure_one()
        for event in self.restagrup_event_ids.filtered(lambda e: e.state == 'draft' and e.city):
            event.action_search_restaurants()
        return self.action_view_restaurant_searches()

    def action_search_restaurants(self):
        self.ensure_one()
        if not self.restagrup_city:
            return self.action_view_restaurant_searches()
        search = self.env['restagrup.restaurant.search'].create({
            'lead_id': self.id,
            'city': self.restagrup_city or '',
            'min_capacity': self.restagrup_pax,
        })
        search.action_search()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'restagrup.restaurant.search',
            'res_id': search.id,
            'view_mode': 'form',
            'target': 'current',
        }
