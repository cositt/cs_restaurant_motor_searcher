# -*- coding: utf-8 -*-
"""Reunión 12/11 (4.1/7.6, 3.6/3.7): ventana «Revisar y enviar» antes de cualquier correo a un restaurante o agencia.

El registro que envía (línea del buscador, pedido, ...) implementa:
- ``_restagrup_send_reviewed(subject, body_text, emails, attachments)``: envía con lo revisado.
- ``_restagrup_default_send_emails()``: a quién va si no se elige (solo en envíos a varios).
"""
import json
import re

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize, email_split

# Marcadores que, en un envío a varios, se rellenan con los datos de cada destinatario.
PER_RECORD_PLACEHOLDERS = ('restaurante', 'menu')
EMAIL_SEPARATORS = re.compile(r'[,;\s]+')


class RestagrupSendWizard(models.TransientModel):
    _name = 'restagrup.send.wizard'
    _description = 'Revisar y enviar correo'

    res_model = fields.Char(required=True, readonly=True)
    res_ids = fields.Char(required=True, readonly=True, help='Lista JSON de ids de los registros que envían.')
    is_multi = fields.Boolean(readonly=True)
    candidate_ids = fields.Many2many(
        'res.partner', 'restagrup_send_wizard_candidate_rel', 'wizard_id', 'partner_id', string='Posibles destinatarios')
    recipient_ids = fields.Many2many(
        'res.partner', 'restagrup_send_wizard_recipient_rel', 'wizard_id', 'partner_id', string='Para',
        domain="[('id', 'in', candidate_ids)]",
        help='La ficha y/o sus contactos. Solo se usan los que tienen email.')
    extra_emails = fields.Char(string='Otros emails', help='Separados por comas.')
    subject = fields.Char(string='Asunto', required=True)
    body = fields.Text(string='Mensaje', required=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'restagrup_send_wizard_attachment_rel', 'wizard_id', 'attachment_id', string='Adjuntos')
    recipients_summary = fields.Text(string='Destinatarios', readonly=True)
    chain_res_ids = fields.Char(readonly=True, help='Lista JSON de los registros que envían después (uno por ventana).')
    chain_method = fields.Char(readonly=True, help='Método que abre la ventana del siguiente registro de la cadena.')

    # --- apertura ---

    @api.model
    def _open_for(self, records, subject, body_text, partner=None, title=None, attachments=None, summary='',
                  chain_method=None):
        """Crea la ventana para `records` y devuelve la acción que la abre. Con un solo registro se eligen los
        destinatarios entre `partner` y sus contactos; con varios, cada uno recibe en su email.
        Con `chain_method`, al enviar se abre la ventana del siguiente registro de ``restagrup_send_chain`` (en el
        contexto): «enviar a todos los restaurantes», uno detrás de otro."""
        is_multi = len(records) > 1 or bool(summary)
        chain = list(self.env.context.get('restagrup_send_chain') or []) if chain_method else []
        values = {
            'chain_res_ids': json.dumps(chain) if chain else False,
            'chain_method': chain_method if chain else False,
            'res_model': records._name,
            'res_ids': json.dumps(records.ids),
            'is_multi': is_multi,
            'subject': subject,
            'body': body_text,
            'recipients_summary': summary,
            'attachment_ids': [Command.set(attachments.ids)] if attachments else [],
        }
        if not is_multi:
            values.update(self._recipient_defaults(records, partner))
        wizard = self.create(values)
        return {
            'type': 'ir.actions.act_window',
            'name': title or _('Revisar y enviar'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(self.env.ref('restagrup_restaurants.view_restagrup_send_wizard_form').id, 'form')],
            'target': 'new',
        }

    @api.model
    def _recipient_defaults(self, record, partner):
        partner = partner or self.env['res.partner']
        contacts = partner.child_ids.filtered(lambda contact: contact.active and (contact.email or '').strip())
        candidates = partner | contacts
        default_email = (record._restagrup_default_send_emails() or [''])[0]
        chosen = candidates.filtered(lambda candidate: email_normalize(candidate.email or '') == email_normalize(
            default_email or ''))[:1]
        extra = '' if chosen or not default_email else default_email
        return {
            'candidate_ids': [Command.set(candidates.ids)],
            'recipient_ids': [Command.set(chosen.ids)],
            'extra_emails': extra,
        }

    @api.model
    def _draft_attachment(self, name, raw):
        """Adjunto para la ventana; al enviar, message_post lo pasa al mensaje (res_model mail.compose.message)."""
        return self.env['ir.attachment'].create({
            'name': name, 'raw': raw, 'res_model': 'mail.compose.message', 'res_id': 0,
        })

    # --- envío ---

    def _records(self):
        self.ensure_one()
        return self.env[self.res_model].browse(json.loads(self.res_ids)).exists()

    def _chosen_emails(self):
        """Emails de los destinatarios elegidos más los escritos a mano, sin repetir y en orden."""
        self.ensure_one()
        typed = [part for part in EMAIL_SEPARATORS.split(self.extra_emails or '') if part]
        invalid = [part for part in typed if not email_split(part)]
        if invalid:
            raise UserError(_('Estos emails no son válidos: %s') % ', '.join(invalid))
        emails, seen = [], set()
        for email in [partner.email for partner in self.recipient_ids if partner.email] + typed:
            key = email_normalize(email) or email.strip().lower()
            if key not in seen:
                seen.add(key)
                emails.append(email.strip())
        return emails

    def _fill_for(self, text, record):
        values = record._mail_values(self.env.user.name) if hasattr(record, '_mail_values') else {}
        for key in PER_RECORD_PLACEHOLDERS:
            text = text.replace('{%s}' % key, str(values.get(key, '')))
        return text

    def action_send(self):
        self.ensure_one()
        records = self._records()
        if not records:
            raise UserError(_('El registro de este correo ya no existe.'))
        if not (self.subject or '').strip() or not (self.body or '').strip():
            raise UserError(_('Escribe el asunto y el mensaje.'))
        if self.is_multi:
            for record in records:
                record._restagrup_send_reviewed(
                    self._fill_for(self.subject, record), self._fill_for(self.body, record),
                    record._restagrup_default_send_emails(), self.attachment_ids)
            return self._after_multi_send(records)
        emails = self._chosen_emails()
        if not emails:
            raise UserError(_('Elige al menos un destinatario con email o escribe uno en «Otros emails».'))
        result = records._restagrup_send_reviewed(self.subject, self.body, emails, self.attachment_ids)
        following = self._open_next_in_chain()
        if following:
            return following
        if isinstance(result, dict):
            return result
        return {'type': 'ir.actions.act_window_close', 'infos': {'reload': True}}

    def _open_next_in_chain(self):
        chain = json.loads(self.chain_res_ids or '[]')
        if not (chain and self.chain_method):
            return None
        following = self.env[self.res_model].browse(chain[0]).exists()
        rest = chain[1:]
        if not following:
            return None
        result = getattr(following.with_context(restagrup_send_chain=rest), self.chain_method)()
        return result if isinstance(result, dict) else None

    def _after_multi_send(self, records):
        hook = getattr(records, '_restagrup_after_multi_send', None)
        if hook:
            return hook()
        return {'type': 'ir.actions.act_window_close', 'infos': {'reload': True}}
