# -*- coding: utf-8 -*-
"""El menú que manda el restaurante en su respuesta: la IA lo guarda en su ficha y lo deja asignado a la línea."""
import io
import logging
import unicodedata

from odoo import _, api, fields, models
from odoo.tools.pdf import PdfReader

from .restaurant_menu import COURSES, MENU_TYPES

_logger = logging.getLogger(__name__)

MENU_TYPE_KEYS = {key for key, _label in MENU_TYPES}
COURSE_KEYS = {key for key, _label in COURSES}
MAX_ATTACHMENT_CHARS = 6000


def _normalized(name):
    text = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode()
    return ' '.join(text.lower().split())


def _number(value):
    try:
        return float(value) if value not in (None, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


def _attachment_text(attachments):
    """Texto de los PDF adjuntos de la respuesta (las imágenes no se leen). Un adjunto roto se salta."""
    parts = []
    for attachment in attachments or []:
        fname, content = attachment[0], attachment[1]
        if not (fname or '').lower().endswith('.pdf') or not content:
            continue
        try:
            reader = PdfReader(io.BytesIO(content if isinstance(content, bytes) else content.encode()))
            text = '\n'.join((page.extract_text() or '') for page in reader.pages).strip()
        except Exception:  # noqa: BLE001 -- un PDF que no se puede leer no debe parar la respuesta
            _logger.info('Adjunto %s no legible como PDF', fname)
            continue
        if text:
            parts.append('--- Adjunto %s ---\n%s' % (fname, text[:MAX_ATTACHMENT_CHARS]))
    return '\n\n'.join(parts)


class RestaurantMenu(models.Model):
    _inherit = 'restagrup.restaurant.menu'

    ai_pending_review = fields.Boolean(
        string='Creado por IA · sin revisar', copy=False, index=True,
        help='La IA lo sacó de la respuesta del restaurante. Revísalo y pulsa «Revisado».')
    source_line_id = fields.Many2one(
        'restagrup.restaurant.search.line', string='Sacado de la respuesta de', copy=False, ondelete='set null',
        readonly=True)
    similar_menu_id = fields.Many2one(
        'restagrup.restaurant.menu', string='Ya había uno parecido', copy=False, ondelete='set null', readonly=True,
        help='Menú del mismo restaurante con el mismo nombre que ya existía. No se ha tocado: este es nuevo.')

    def action_mark_reviewed(self):
        self.write({'ai_pending_review': False})

    def _restagrup_dishes(self):
        return sorted((line.course, _normalized(line.name)) for line in self.line_ids)


class RestaurantSearchLine(models.Model):
    _inherit = 'restagrup.restaurant.search.line'

    def _restagrup_menu_vals(self, data):
        menu_type = (data.get('tipo') or '').strip().lower()
        dishes = [d for d in (data.get('platos') or []) if isinstance(d, dict) and (d.get('nombre') or '').strip()]
        return {
            'name': (data.get('nombre') or '').strip() or _('Menú %s') % (self.partner_id.name or ''),
            'partner_id': self.partner_id.id,
            'menu_type': menu_type if menu_type in MENU_TYPE_KEYS else 'sin_definir',
            'cost_price': _number(data.get('precio_persona')),
            'drinks_included': bool((data.get('bebidas') or '').strip()),
            'drinks_description': (data.get('bebidas') or '').strip() or False,
            'min_pax': int(_number(data.get('min_comensales'))),
            'max_pax': int(_number(data.get('max_comensales'))),
            'line_ids': [(0, 0, {
                'course': (d.get('tipo') or '').strip().lower() if (d.get('tipo') or '').strip().lower() in COURSE_KEYS
                else 'otro',
                'name': d['nombre'].strip(), 'sequence': index,
            }) for index, d in enumerate(dishes)],
            'ai_pending_review': True,
            'source_line_id': self.id,
        }

    def _restagrup_store_menu(self, data):
        """Guarda un menú de la respuesta. Uno igual (nombre, precio y platos) se reutiliza; uno con el mismo
        nombre pero distinto se crea aparte, con la fecha en el nombre, y se avisa."""
        Menu = self.env['restagrup.restaurant.menu']
        vals = self._restagrup_menu_vals(data)
        same_name = Menu.search([('partner_id', '=', self.partner_id.id)]).filtered(
            lambda m: _normalized(m.name) == _normalized(vals['name']))
        dishes = sorted((cmd[2]['course'], _normalized(cmd[2]['name'])) for cmd in vals['line_ids'])
        for menu in same_name:
            if round(menu.cost_price, 2) == round(vals['cost_price'], 2) and menu._restagrup_dishes() == dishes:
                return menu
        if same_name:
            today = fields.Date.context_today(self).strftime('%d/%m/%Y')
            vals.update(name='%s (%s)' % (vals['name'], today), similar_menu_id=same_name[:1].id)
        menu = Menu.create(vals)
        note = _('%(restaurant)s: menú «%(menu)s» guardado en su ficha desde su respuesta (creado por IA, sin revisar).')
        if menu.similar_menu_id:
            note += ' ' + _('Ya había uno parecido («%s»): no se ha tocado, revisa cuál vale.') % menu.similar_menu_id.name
        self.search_id.message_post_if_exists(note % {'restaurant': self.name, 'menu': menu.name})
        return menu

    def _restagrup_menus_from_reply(self, menus):
        """Guarda los menús que trae la respuesta y asigna el primero a la línea si aún no tiene."""
        self.ensure_one()
        menus = [m for m in (menus or []) if isinstance(m, dict)]
        if not menus:
            return self.env['restagrup.restaurant.menu']
        if not self.partner_id:
            # Sin ficha no hay dónde guardar el menú: se crea (o se enlaza la que ya exista).
            self.action_add_as_partner()
            self.search_id.message_post_if_exists(_(
                '%s mandó su menú y se ha añadido como contacto para guardarlo en su ficha.') % self.name)
        stored = self.env['restagrup.restaurant.menu']
        for data in menus:
            stored |= self._restagrup_store_menu(data)
        if not self.menu_id:
            self.menu_id = stored[:1]
        self._restagrup_ask_missing_menu_data(menus)
        return stored

    # --- lo que falta en la respuesta ---

    @api.model
    def _restagrup_menu_missing(self, data, amount):
        missing = []
        if not _number(data.get('precio_persona')) and not amount:
            missing.append(_('Precio por persona'))
        courses = {(d.get('tipo') or '').strip().lower() for d in (data.get('platos') or []) if isinstance(d, dict)}
        if not (data.get('bebidas') or '').strip() and 'bebida' not in courses:
            missing.append(_('Bebidas'))
        if courses and 'postre' not in courses:
            missing.append(_('Postre'))
        return missing

    def _restagrup_ask_missing_menu_data(self, menus):
        missing = []
        for data in menus:
            missing += [item for item in self._restagrup_menu_missing(data, self.quote_amount) if item not in missing]
        if not missing:
            return
        queue = self.env['restagrup.pending.mail']
        if queue.search_count([('line_id', '=', self.id), ('kind', '=', 'quote_incomplete'), ('state', '!=', 'error')]):
            return
        subject, body = self._quote_incomplete_content(missing, self.search_id.user_id.name or self.env.company.name)
        if queue._is_automatic('quote_incomplete'):
            self._post_email(subject, body, self._get_quote_email_to())
            return
        queue.create({
            'kind': 'quote_incomplete', 'line_id': self.id, 'recipient_email': self._get_quote_email_to(),
            'subject': subject, 'body': body, 'reason': _('Faltan datos en su respuesta: %s') % ', '.join(missing),
        })

    def _quote_incomplete_content(self, missing, signer):
        values = dict(self._mail_values(signer), faltan='\n'.join('- %s' % item for item in missing))

        def fallback():
            return (_('Datos que faltan de vuestro presupuesto'),
                    '\n'.join([_('Buenos días,'), '', _('Gracias por tu información, salvo error, faltaría saber:'),
                               '', values['faltan'], '', _('Gracias!'), signer]))

        return self.env['restagrup.mail.template']._compose('quote_incomplete', values, fallback)
