# -*- coding: utf-8 -*-
"""A3: datos de grupo de la ficha del restaurante -- petición de los que faltan y lectura con IA de la respuesta."""
import json

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

EXTRACT_DATA_SYSTEM_PROMPT = """\
Eres un asistente que lee la respuesta de un restaurante a la petición de los datos de su
ficha para grupos. Devuelve SOLO un objeto JSON, sin texto adicional, con estas claves
exactas: "aforo" (número entero de comensales para grupos, o null), "dia_cierre" (uno de
"mon","tue","wed","thu","fri","sat","sun" -- lunes a domingo --, o "none" si abre todos los
días, o null si no lo dicen), "idioma" (código ISO de dos letras del idioma de contacto, o
null), "responsable" (nombre de la persona que lleva los grupos, o null), "movil" (su móvil,
o null), "gratuidades" (texto corto con las condiciones de gratuidad, o null), "parking_bus"
(true si confirman que tienen parking de autobús, si no null).
Si un dato no aparece claramente en el texto, pon null -- nunca lo inventes."""

WEEKDAY_CODES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'none')


def _clean_text(value):
    text = str(value).strip() if value not in (None, False) else ''
    return text or None


def _clean_capacity(value):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_weekday(value):
    return value if value in WEEKDAY_CODES else None


def _clean_true(value):
    return True if value is True else None


# clave de la IA -> (campo del contacto, limpiador del valor; devuelve None si no vale)
PROPOSAL_FIELDS = {
    'aforo': ('restaurant_capacity', _clean_capacity),
    'dia_cierre': ('restaurant_closed_weekday', _clean_weekday),
    'idioma': ('restaurant_language', _clean_text),
    'responsable': ('restaurant_group_manager', _clean_text),
    'movil': ('restaurant_group_mobile', _clean_text),
    'gratuidades': ('restaurant_gratuities', _clean_text),
    'parking_bus': ('restaurant_bus_parking', _clean_true),
}


class RestaurantSearchLineData(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    data_request_date = fields.Datetime(
        string='Datos pedidos el', copy=False,
        help='Cuándo se pidió al restaurante los datos que faltan en su ficha. Una respuesta posterior se lee '
             'como datos de ficha, no como presupuesto.',
    )
    data_proposal = fields.Text(
        string='Datos propuestos por IA', copy=False,
        help='JSON {campo del contacto: valor} que la IA sacó de la respuesta. No se aplica hasta que una persona '
             'lo confirma.',
    )
    data_proposal_summary = fields.Char(string='Datos propuestos', compute='_compute_data_proposal_summary')

    def _compute_data_proposal_summary(self):
        partner_fields = self.env['res.partner']._fields
        for line in self:
            proposal = json.loads(line.data_proposal) if line.data_proposal else {}
            parts = []
            for name, value in proposal.items():
                field = partner_fields[name]
                if field.type == 'selection':
                    value = dict(field.selection).get(value, value)
                elif field.type == 'boolean':
                    value = _('Sí')
                parts.append('%s: %s' % (field.string, value))
            line.data_proposal_summary = ' · '.join(parts)

    # --- pedir los datos ---

    def _data_request_content(self, signer_name):
        """Asunto y texto del correo que pide al restaurante solo los datos que faltan en su ficha."""
        self.ensure_one()
        missing = self.partner_id._restaurant_missing_labels()
        subject = _('Datos para trabajar con grupos — %s') % self.env.company.name
        lines = [
            _('Hola,'), '',
            _('Para poder proponeros grupos nos faltan estos datos de %s:') % self.name, '',
        ] + ['- %s' % label for label in missing] + ['', _('Gracias,'), signer_name]
        return subject, '\n'.join(lines)

    def action_request_missing_data(self):
        """Pide al restaurante los datos vacíos de su ficha. Con el modo «con aprobación» el correo va a la
        cola Pendientes de aprobar; en automático sale ya."""
        self.ensure_one()
        queue = self.env['restagrup.pending.mail']
        if not self.partner_id.restaurant_is_incomplete:
            raise UserError(_('La ficha de este restaurante ya está completa (o aún no es un contacto).'))
        email_to = self._get_quote_email_to()  # sin email no hay a quién pedírselo
        if queue._send_mode() == 'automatic':
            subject, body = self._data_request_content(self.env.user.name)
            self._post_email(subject, body, email_to)
            self._mark_data_requested()
            return
        queue._enqueue_data_request(self)

    def _mark_data_requested(self):
        self.write({'data_request_date': fields.Datetime.now()})

    # --- leer la respuesta ---

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for line in self:
            line._restagrup_classify_data_response(msg_dict)
        return res

    def _restagrup_classify_data_response(self, msg_dict):
        """Propone los datos de ficha que da la respuesta a «Pedir datos que faltan». Nunca escribe en el
        contacto: deja la propuesta para que una persona la aplique."""
        self.ensure_one()
        if not self.data_request_date or not self.partner_id.restaurant_is_incomplete:
            return
        raw_body = msg_dict.get('body') or ''
        text = html2plaintext(raw_body).strip() if raw_body else ''
        if not text:
            return
        data, provider = self.env['restagrup.llm.connector'].extract_json(EXTRACT_DATA_SYSTEM_PROMPT, text)
        proposal = self._clean_data_proposal(data)
        if not proposal:
            return
        self.data_proposal = json.dumps(proposal)
        self.search_id.message_post_if_exists(_(
            '%(name)s: datos de ficha extraídos por IA (%(provider)s) — revísalos y aplícalos en la tarjeta.'
        ) % {'name': self.name, 'provider': provider})

    @staticmethod
    def _clean_data_proposal(data):
        """Solo claves conocidas con valores válidos; lo demás se descarta sin error."""
        if not isinstance(data, dict):
            return {}
        proposal = {}
        for key, (field_name, clean) in PROPOSAL_FIELDS.items():
            value = clean(data.get(key))
            if value is not None:
                proposal[field_name] = value
        return proposal

    # --- aplicar o descartar ---

    def action_apply_data_proposal(self):
        """Pasa la propuesta al contacto rellenando solo lo que está vacío: lo que alguien escribió no se pisa."""
        self.ensure_one()
        proposal = json.loads(self.data_proposal) if self.data_proposal else {}
        partner = self.partner_id
        vals = {name: value for name, value in proposal.items() if value and not partner[name]}
        if vals:
            partner.write(vals)
        self.data_proposal = False
        self.search_id.message_post_if_exists(_(
            '%(name)s: datos de ficha aplicados por %(user)s (%(count)s campos).'
        ) % {'name': self.name, 'user': self.env.user.name, 'count': len(vals)})

    def action_discard_data_proposal(self):
        self.write({'data_proposal': False})
