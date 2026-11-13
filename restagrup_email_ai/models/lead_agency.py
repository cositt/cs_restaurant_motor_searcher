# -*- coding: utf-8 -*-
"""Título del grupo y agencia a partir de lo que lee la IA (PPT de Conchita 2026-11-04, diapositivas 1 y 2).

- El título de la petición es la referencia del grupo («Colegio Teresianas»); si no la hay, el tipo de grupo
  («Grupo escolar») y, por defecto, «Grupo adulto».
- Quien escribe es el contacto; la agencia es su empresa. Si la agencia ya existe (por nombre o por el dominio de
  su correo) se usa; si no, se crea con los datos de la firma. Lo que ya tenía una ficha nunca se pisa."""
import re
import unicodedata

from odoo import _, fields, models
from odoo.tools import email_normalize
from odoo.tools.mail import parse_contact_from_email

GROUP_TITLES = {
    'escolar': 'Grupo escolar',
    'deportivo': 'Grupo deportivo',
    'senior': 'Grupo senior',
}
DEFAULT_GROUP_TITLE = 'Grupo adulto'
GENERIC_MAIL_DOMAINS = frozenset({
    'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.es', 'outlook.com', 'outlook.es', 'live.com',
    'yahoo.com', 'yahoo.es', 'icloud.com', 'me.com', 'msn.com', 'aol.com', 'gmx.com', 'gmx.es', 'proton.me',
    'protonmail.com', 'telefonica.net', 'movistar.es', 'orange.es', 'terra.es',
})
SIGNATURE_FIELDS = {'telefono': 'phone', 'direccion': 'street', 'codigo_postal': 'zip', 'ciudad': 'city',
                    'web': 'website'}


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _street_only(street, signature):
    """Quita de la calle el código postal y la ciudad si la IA copió la línea entera («Calle Larios 5, 29005 Málaga»)."""
    for key in ('ciudad', 'codigo_postal'):
        part = _text(signature.get(key))
        if part and street.endswith(part):
            street = street[:-len(part)].rstrip(' ,-·')
    return street


# Lo que no distingue a una agencia de otra al comparar nombres («Sol y Nubes S.L.» = «SOL Y NUBES»).
LEGAL_SUFFIXES = re.compile(r'\b(s\.?\s?l\.?u?|s\.?\s?a\.?|sociedad limitada|viajes|agencia de viajes)\b')


def _agency_key(name):
    text = unicodedata.normalize('NFKD', _text(name).casefold())
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ' '.join(LEGAL_SUFFIXES.sub(' ', re.sub(r'[^\w\s.]', ' ', text)).replace('.', ' ').split())


def _same_agency(first, second):
    a, b = _agency_key(first), _agency_key(second)
    return bool(a and b) and (a == b or a in b or b in a)


def _mail_domain(email):
    email = email_normalize(email or '') or ''
    return email.rpartition('@')[2] if '@' in email else ''


class CrmLeadAgency(models.Model):
    _inherit = 'crm.lead'

    restagrup_agency_warning = fields.Char(
        string='Aviso de agencia', copy=False,
        help='Reunión 12/11 (2.1): el correo nombra una agencia distinta de la de quien escribe. No se asigna a'
             ' ciegas: lo revisa una persona.')

    # --- título ---

    def _restagrup_set_group_title(self, reference, group_type):
        self.ensure_one()
        title = _text(reference) or GROUP_TITLES.get(_text(group_type).lower(), DEFAULT_GROUP_TITLE)
        self.name = title

    # --- agencia y contacto ---

    def _restagrup_set_agency(self, name, signature=None):
        """Enlaza (o crea) el contacto de quien escribe y su agencia."""
        self.ensure_one()
        name = _text(name)
        signature = signature if isinstance(signature, dict) else {}
        if name:
            self.partner_name = name
        contact = self._restagrup_find_or_create_contact(signature)
        if not contact:
            return
        if self.partner_id != contact:
            self.sudo().partner_id = contact  # un lead sin asignar no es escribible por todos los comerciales
        if name and contact.parent_id and not _same_agency(name, contact.parent_id.name):
            # Hallazgo guía 13/11: la empresa del lead es la de quien escribe, no la que nombra el correo.
            self.partner_name = contact.parent_id.name
            self._restagrup_warn_agency_mismatch(name, contact)
        if name and not contact.is_company and not contact.parent_id:
            contact.sudo().parent_id = self._restagrup_find_or_create_agency(name, signature)
        if contact.parent_id:
            self._restagrup_complete_agency(contact.parent_id, signature)

    def _restagrup_warn_agency_mismatch(self, named, contact):
        """Reunión 12/11 (2.1): el correo habla de una agencia y quien escribe es de otra (Peregrino Travel / Sol
        y Nubes). Se deja la de quien escribe y se avisa para que una persona decida."""
        warning = _('El correo nombra la agencia «%(named)s», pero %(contact)s es de «%(agency)s». Revisa cuál es'
                    ' la agencia del grupo.', named=named, contact=contact.name, agency=contact.parent_id.name)
        self.sudo().restagrup_agency_warning = warning
        self.sudo().message_post(body=warning, subtype_xmlid='mail.mt_note')

    def action_dismiss_agency_warning(self):
        """Hallazgo guía 13/11: una persona ya lo ha revisado; el aviso desaparece."""
        self.sudo().restagrup_agency_warning = False

    def write(self, vals):
        # Si cambian el cliente, el aviso de agencia ya está resuelto (lo decidió una persona).
        if 'partner_id' in vals and 'restagrup_agency_warning' not in vals:
            changed = self.filtered(lambda lead: lead.restagrup_agency_warning
                                    and lead.partner_id.id != vals['partner_id'])
            result = super().write(vals)
            if changed:
                changed.sudo().restagrup_agency_warning = False
            return result
        return super().write(vals)

    def _restagrup_partner_domain(self):
        """Contactos que pueden ser la agencia o su gente: nunca un restaurante."""
        if 'is_restaurant' in self.env['res.partner']._fields:
            return [('is_restaurant', '=', False)]
        return []

    def _restagrup_find_or_create_contact(self, signature):
        if self.partner_id:
            return self.partner_id
        email = email_normalize(self.email_from or '')
        if not email:
            return self.env['res.partner']
        Partner = self.env['res.partner'].sudo()
        contact = Partner.search([('email_normalized', '=', email)] + self._restagrup_partner_domain(),
                                 order='id', limit=1)
        if contact:
            return contact
        person = _text(signature.get('nombre')) or self.contact_name or parse_contact_from_email(
            self.email_from)[0] or email
        return Partner.create({'name': person, 'email': email})

    def _restagrup_find_or_create_agency(self, name, signature):
        Partner = self.env['res.partner'].sudo()
        base = [('is_company', '=', True)] + self._restagrup_partner_domain()
        agency = Partner.search(base + [('name', '=ilike', name)], limit=1)
        domain = _mail_domain(self.email_from)
        if not agency and domain and domain not in GENERIC_MAIL_DOMAINS:
            agency = Partner.search(base + [('email_normalized', '=ilike', '%@' + domain)], limit=1)
        if not agency:
            agency = Partner.create({'name': name, 'is_company': True})
        return agency

    def _restagrup_complete_agency(self, agency, signature):
        """Rellena con la firma lo que le falte a la ficha de la agencia; lo que ya tenía no se toca."""
        vals = {}
        for key, field in SIGNATURE_FIELDS.items():
            value = _text(signature.get(key))
            if key == 'direccion':
                value = _street_only(value, signature)
            if value and not agency[field]:
                vals[field] = value
        if vals:
            agency.sudo().write(vals)
