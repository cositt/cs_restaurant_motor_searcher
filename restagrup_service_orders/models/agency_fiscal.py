# -*- coding: utf-8 -*-
"""Datos fiscales de la agencia (PPT de Conchita 2026-11-04, diapositiva 2). Al firmar el presupuesto, si a la
agencia le falta el CIF o la razón social, se prepara un correo pidiéndoselos, con lo que ya tenemos para que lo
revise. Va por la cola de aprobación (salvo que su plantilla salga sola) y se pide una vez por agencia."""
import logging

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

KIND = 'agency_fiscal_request'


class ResPartnerLegalName(models.Model):
    _inherit = 'res.partner'

    restagrup_legal_name = fields.Char(
        string='Razón social', help='Nombre fiscal de la empresa, el que va en las facturas (si no es el comercial).')

    def _restagrup_fiscal_missing(self):
        """Lo que le falta a la empresa para facturarle."""
        self.ensure_one()
        missing = []
        if not self.vat:
            missing.append(_('CIF'))
        if not self.restagrup_legal_name:
            missing.append(_('Razón social'))
        return missing

    def _restagrup_fiscal_known(self):
        self.ensure_one()
        address = ', '.join(part for part in (self.street, self.zip, self.city) if part)
        rows = [(_('Nombre'), self.name), (_('Razón social'), self.restagrup_legal_name), (_('CIF'), self.vat),
                (_('Dirección'), address), (_('Teléfono'), self.phone), (_('Correo'), self.email)]
        return '\n'.join('- %s: %s' % (label, value) for label, value in rows if value)


class CrmLeadAgencyFiscal(models.Model):
    _inherit = 'crm.lead'

    def _restagrup_fiscal_agency(self):
        """La agencia a la que se factura: solo si es una empresa (a un particular no se le pide)."""
        self.ensure_one()
        agency = self.partner_id.commercial_partner_id
        return agency if agency.is_company else self.env['res.partner']

    def _restagrup_ask_agency_fiscal_data(self):
        self.ensure_one()
        agency = self._restagrup_fiscal_agency()
        missing = agency._restagrup_fiscal_missing() if agency else []
        email_to = self._restagrup_agency_email()
        if not missing or not email_to or self._restagrup_fiscal_already_asked(agency):
            return False
        subject, body = self._restagrup_fiscal_content(agency, missing)
        queue = self.env['restagrup.pending.mail']
        if queue._is_automatic(KIND):
            self._restagrup_post_mail(subject, body, email_to)
        else:
            queue.create({
                'kind': KIND, 'request_lead_id': self.id, 'recipient_email': email_to, 'subject': subject,
                'body': body, 'reason': _('A la agencia le falta: %s') % ', '.join(missing),
            })
        return True

    def _restagrup_fiscal_already_asked(self, agency):
        queue = self.env['restagrup.pending.mail'].sudo()
        asked = queue.search([('kind', '=', KIND), ('state', 'in', ('pending', 'sent'))])
        return any(mail.request_lead_id._restagrup_fiscal_agency() == agency for mail in asked)

    def _restagrup_fiscal_content(self, agency, missing):
        values = {
            'agencia': agency.name, 'datos': agency._restagrup_fiscal_known(),
            'faltan': '\n'.join('- %s' % item for item in missing), 'firma': self.env.user.name,
            'localizador': self._restagrup_locator() or '',
        }

        def fallback():
            return (_('Datos de facturación de %(agencia)s') % values,
                    _('Hola,\n\nPara poder emitir la factura de vuestra reserva necesitamos completar los datos de '
                      'facturación de %(agencia)s. Esto es lo que tenemos:\n\n%(datos)s\n\nNos faltaría:\n\n'
                      '%(faltan)s\n\n¿Nos lo podéis indicar respondiendo a este correo? Si algo de lo que tenemos '
                      'no es correcto, decídnoslo también.\n\nGracias,\n%(firma)s') % values)

        return self.env['restagrup.mail.template']._compose(KIND, values, fallback)

    def _restagrup_post_mail(self, subject, body_text, email_to):
        """Por el hilo del grupo: la respuesta de la agencia vuelve al mismo grupo."""
        self.ensure_one()
        self.message_post(
            body=Markup('<br/>').join(Markup.escape(line) for line in body_text.splitlines()),
            subject=subject, message_type='email', subtype_xmlid='mail.mt_comment',
            email_from=self.env['restagrup.system.mail'].email_from(self.user_id.email or self.env.user.email),
            email_add_signature=False,  # el texto ya lleva {firma}
            outgoing_email_to=email_to,
        )


class SaleOrderAgencyFiscal(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        res = super().action_confirm()
        for lead in self.opportunity_id:
            try:
                with self.env.cr.savepoint():
                    lead._restagrup_ask_agency_fiscal_data()
            except Exception:  # noqa: BLE001 -- pedir datos fiscales nunca debe impedir confirmar la venta
                _logger.exception('No se pudo preparar la petición de datos fiscales para %s', lead.name)
        return res


class PendingMailAgencyFiscal(models.Model):
    _inherit = 'restagrup.pending.mail'

    kind = fields.Selection(selection_add=[(KIND, 'Datos fiscales de la agencia')], ondelete={KIND: 'cascade'})

    def _still_applies_agency_fiscal_request(self):
        lead = self.request_lead_id
        agency = lead._restagrup_fiscal_agency() if lead else self.env['res.partner']
        return bool(agency and agency._restagrup_fiscal_missing())

    def _send_agency_fiscal_request(self):
        if not self.recipient_email:
            raise UserError(_('Este correo no tiene destinatario.'))
        self.request_lead_id._restagrup_post_mail(self.subject, self.body, self.recipient_email)
