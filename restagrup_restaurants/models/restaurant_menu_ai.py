# -*- coding: utf-8 -*-
"""El menú que manda el restaurante en su respuesta: la IA lo guarda en su ficha y lo deja asignado a la línea."""
import io
import logging
import re
import unicodedata

from odoo import _, api, fields, models
from odoo.tools.pdf import PdfReader

from .restaurant_menu import COURSES, MENU_TYPES, name_with_season

_logger = logging.getLogger(__name__)

MENU_TYPE_KEYS = {key for key, _label in MENU_TYPES}
COURSE_KEYS = {key for key, _label in COURSES}
MAX_ATTACHMENT_CHARS = 6000
COMBINED_PLATE = re.compile(r'\bplatos? combinados?\b', re.IGNORECASE)
# Reunión 23/11: desde este parecido entre los platos se avisa de que ya hay un menú casi igual en la ficha.
DUPLICATE_DISH_OVERLAP = 0.5
DEFAULT_MENU_NAME = 'menu grupos'


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
            # Reunión 12/11 (8.2): sin nombre, «Menú grupos»; el año (de la fecha del servicio) lo pone el menú.
            'name': (data.get('nombre') or '').strip() or _('Menú grupos'),
            'season': self._restagrup_menu_season(),
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

    def _restagrup_menu_season(self):
        """Año del servicio para el que se pidió el menú; sin fecha, el actual."""
        self.ensure_one()
        event_date = self.search_id.event_id.event_date
        return event_date.year if event_date else fields.Date.context_today(self).year

    def _restagrup_store_menu(self, data):
        """Guarda un menú de la respuesta. Uno igual (nombre, precio y platos) se reutiliza; uno con el mismo
        nombre pero distinto se crea aparte, con la fecha en el nombre, y se avisa."""
        Menu = self.env['restagrup.restaurant.menu']
        vals = self._restagrup_menu_vals(data)
        vals['name'] = name_with_season(vals['name'], vals['season'])
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

    # --- menús que ya existen (reunión 23/11) ---

    menu_name = fields.Char(
        related='menu_id.name', readonly=False, string='Nombre del menú',
        help='Corrígelo aquí si la IA no encontró el nombre del menú en la respuesta.')
    menu_name_is_default = fields.Boolean(
        compute='_compute_menu_name_is_default',
        help='El menú lo creó la IA sin nombre propio y lleva el nombre por defecto.')

    @api.depends('menu_id.name', 'menu_id.ai_pending_review')
    def _compute_menu_name_is_default(self):
        for line in self:
            menu = line.menu_id
            line.menu_name_is_default = bool(
                menu and menu.ai_pending_review and _normalized(menu.name).startswith(DEFAULT_MENU_NAME))

    @staticmethod
    def _normalized_dish(name):
        return _normalized(name)

    @staticmethod
    def _restagrup_data_dishes(data):
        return {_normalized(d.get('nombre')) for d in (data.get('platos') or [])
                if isinstance(d, dict) and (d.get('nombre') or '').strip()}

    def _restagrup_menu_match(self, data, menu):
        """(es idéntico, se parece) de un menú de la respuesta con uno que ya está en la ficha. Se parece si lleva el
        mismo nombre o comparte la mitad de los platos."""
        season = self._restagrup_menu_season()
        name = _normalized(name_with_season((data.get('nombre') or '').strip() or _('Menú grupos'), season))
        dishes = self._restagrup_data_dishes(data)
        menu_dishes = {_normalized(line.name) for line in menu.line_ids}
        union = dishes | menu_dishes
        overlap = len(dishes & menu_dishes) / len(union) if union else 0.0
        same_name = _normalized(menu.name) == name
        identical = (same_name and round(menu.cost_price, 2) == round(_number(data.get('precio_persona')), 2)
                     and dishes == menu_dishes)
        return identical, (same_name or overlap >= DUPLICATE_DISH_OVERLAP), overlap

    def _restagrup_menu_matches(self, menus):
        """[(posición, menú de la ficha, idéntico)] con el menú más parecido de cada uno de la respuesta, solo de los
        que ya tienen uno igual o casi igual."""
        self.ensure_one()
        menus = [m for m in (menus or []) if isinstance(m, dict)]
        if not self.partner_id:
            return []
        stored = self.env['restagrup.restaurant.menu'].search([('partner_id', '=', self.partner_id.id)])
        matches = []
        for index, data in enumerate(menus):
            scored = []
            for menu in stored:
                identical, similar, overlap = self._restagrup_menu_match(data, menu)
                if similar:
                    scored.append((identical, overlap, menu))
            if scored:
                identical, _overlap, menu = max(scored, key=lambda row: (row[0], row[1]))
                matches.append((index, menu, identical))
        return matches

    def _restagrup_menus_from_reply(self, menus, reuse=None):
        """Guarda los menús que trae la respuesta y asigna el primero a la línea si aún no tiene.
        `reuse` ({posición: menú}) son los que la persona decidió no duplicar."""
        self.ensure_one()
        reuse = reuse or {}
        menus = [m for m in (menus or []) if isinstance(m, dict)]
        if not menus:
            return self.env['restagrup.restaurant.menu']
        if not self.partner_id:
            # Sin ficha no hay dónde guardar el menú: se crea (o se enlaza la que ya exista).
            self.action_add_as_partner()
            self.search_id.message_post_if_exists(_(
                '%s mandó su menú y se ha añadido como contacto para guardarlo en su ficha.') % self.name)
        stored = self.env['restagrup.restaurant.menu']
        for index, data in enumerate(menus):
            stored |= reuse.get(index) or self._restagrup_store_menu(data)
        if not self.menu_id:
            self.menu_id = stored[:1]
        self._restagrup_ask_missing_menu_data(menus)
        return stored

    # --- lo que falta en la respuesta ---

    @api.model
    def _restagrup_is_combined_plate(self, data):
        names = [data.get('nombre') or ''] + [d.get('nombre') or '' for d in (data.get('platos') or [])
                                               if isinstance(d, dict)]
        return any(COMBINED_PLATE.search(name) for name in names)

    @api.model
    def _restagrup_menu_missing(self, data, amount):
        missing = []
        if not _number(data.get('precio_persona')) and not amount:
            missing.append(_('Precio por persona'))
        courses = {(d.get('tipo') or '').strip().lower() for d in (data.get('platos') or []) if isinstance(d, dict)}
        if not (data.get('bebidas') or '').strip() and 'bebida' not in courses:
            missing.append(_('Bebidas'))
        # Reunión 12/11 (6.4): un plato combinado no lleva postre: no se pide.
        if courses and 'postre' not in courses and not self._restagrup_is_combined_plate(data):
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
