# -*- coding: utf-8 -*-
"""Reunión 23/11: un solo botón «Imprimir» con los cuatro PDF que genera Restagrup, en cualquier fase del grupo."""
from odoo import _, fields, models
from odoo.exceptions import UserError

PROPOSAL_REPORT = 'restagrup_agency_proposal.action_report_client_comparison'


class CrmLeadPrint(models.Model):
    _inherit = 'crm.lead'

    def action_open_print_wizard(self):
        self.ensure_one()
        wizard = self.env['restagrup.print.wizard'].create({'lead_id': self.id})
        return {
            'type': 'ir.actions.act_window', 'name': _('Imprimir'), 'res_model': wizard._name,
            'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
        }


class PrintWizard(models.TransientModel):
    _name = 'restagrup.print.wizard'
    _description = 'Imprimir los documentos del grupo'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')

    def action_print_proposal(self):
        """El mismo PDF que se adjunta al enviar la propuesta a la agencia, sin tener que enviarla."""
        self.ensure_one()
        searches = self.lead_id._restagrup_proposal_searches()
        if not searches:
            raise UserError(_('Este grupo aún no tiene ninguna búsqueda de restaurantes: crea la búsqueda y marca'
                              ' los restaurantes para poder imprimir la propuesta.'))
        return self.env.ref(PROPOSAL_REPORT).report_action(searches)

    def action_print_agency(self):
        self.ensure_one()
        return self.lead_id.action_download_agency_confirmation()

    def action_print_restaurant(self):
        self.ensure_one()
        return self.lead_id.action_download_restaurant_confirmation()

    def action_print_voucher(self):
        self.ensure_one()
        return self.lead_id.action_download_voucher()
