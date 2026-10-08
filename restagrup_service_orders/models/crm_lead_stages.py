# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.mail import parse_contact_from_email

SEQUENCE_CODE = 'restagrup.lead.document'
STAGE_MODULE = 'restagrup_service_orders'
STAGE_ORDER = ('peticion', 'presupuesto', 'expediente', 'cerrado')
# Etapas que traía Odoo de serie → fase del flujo de RestaGrup.
OLD_STAGE_MAP = {
    'crm.stage_lead1': 'peticion',
    'crm.stage_lead2': 'presupuesto',
    'crm.stage_lead3': 'presupuesto',
    'crm.stage_lead4': 'cerrado',
}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    restagrup_doc_seq = fields.Integer(string='Nº de documento', copy=False, index=True, readonly=True)
    restagrup_doc_number = fields.Char(
        string='Documento', compute='_compute_restagrup_doc_number', store=True, index=True,
        help='PET/PRE/EXP + año y mes de creación + número. El número no cambia en toda la vida del grupo;'
             ' el prefijo sí, según la fase.',
    )
    restagrup_stage_key = fields.Selection(related='stage_id.restagrup_stage_key', string='Fase')
    restagrup_agency_name = fields.Char(
        string='Agencia', compute='_compute_restagrup_agency_name',
        help='La agencia del grupo; si aún no es un contacto (llegó por correo), lo que dio el remitente.',
    )
    restagrup_first_service_date = fields.Date(
        string='Fecha 1º servicio', compute='_compute_restagrup_first_service', store=True,
    )
    restagrup_first_service_city = fields.Char(string='Población 1º servicio', compute='_compute_restagrup_first_service')
    restagrup_total_pax = fields.Integer(string='Nº comensales', compute='_compute_restagrup_first_service')

    @api.depends('partner_id', 'partner_name', 'contact_name', 'email_from')
    def _compute_restagrup_agency_name(self):
        for lead in self:
            sender_name, sender_email = parse_contact_from_email(lead.email_from) if lead.email_from else ('', '')
            lead.restagrup_agency_name = (
                lead.partner_id.name or lead.partner_name or lead.contact_name or sender_name or sender_email or False)

    # --- numeración ---

    @api.depends('stage_id.restagrup_doc_prefix', 'restagrup_doc_seq', 'create_date')
    def _compute_restagrup_doc_number(self):
        for lead in self:
            if not lead.restagrup_doc_seq:
                lead.restagrup_doc_number = False
                continue
            created = lead.create_date or fields.Datetime.now()
            lead.restagrup_doc_number = '%s%s-%s' % (
                lead.stage_id.restagrup_doc_prefix or 'PET', created.strftime('%Y%m'), lead.restagrup_doc_seq)

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if not vals.get('restagrup_doc_seq'):
                vals['restagrup_doc_seq'] = int(sequence.next_by_code(SEQUENCE_CODE) or 0) or False
        return super().create(vals_list)

    # --- datos para las listas ---

    @api.depends('restagrup_event_ids.event_date', 'restagrup_event_ids.city', 'restagrup_event_ids.pax',
                 'restagrup_city', 'restagrup_pax', 'restagrup_service_date')
    def _compute_restagrup_first_service(self):
        for lead in self:
            events = lead.restagrup_event_ids.sorted(lambda e: (e.event_date or fields.Date.today().replace(year=9999), e.id))
            if events:
                first = events[0]
                lead.restagrup_first_service_date = first.event_date
                lead.restagrup_first_service_city = first.city
                lead.restagrup_total_pax = sum(events.mapped('pax'))
            else:
                lead.restagrup_first_service_date = lead.restagrup_service_date
                lead.restagrup_first_service_city = lead.restagrup_city
                lead.restagrup_total_pax = lead.restagrup_pax

    # --- etapas ---

    def _restagrup_stage(self, key):
        return self.env.ref('%s.stage_%s' % (STAGE_MODULE, key))

    def _restagrup_move_to(self, key):
        for lead in self:
            old = lead.stage_id
            stage = lead._restagrup_stage(key)
            lead.write({'stage_id': stage.id})
            lead.message_post(body=_('Fase: %(old)s → %(new)s.', old=old.name, new=stage.name))

    def _restagrup_advance_to(self, key):
        """Avanza solo hacia delante y en silencio (lo usan los envíos y confirmaciones automáticos)."""
        target = STAGE_ORDER.index(key)
        for lead in self:
            current = lead.restagrup_stage_key
            if current in STAGE_ORDER and STAGE_ORDER.index(current) < target:
                lead._restagrup_move_to(key)

    def _restagrup_require_stage(self, allowed, action):
        for lead in self:
            if lead.restagrup_stage_key not in allowed:
                raise UserError(_('«%(action)s» no se puede hacer desde la fase actual (%(stage)s).',
                                  action=action, stage=lead.stage_id.name))

    def action_pass_to_quote(self):
        self._restagrup_require_stage(('peticion',), _('Pasar a presupuesto'))
        return self._restagrup_gated('pass_to_quote', '_restagrup_do_pass_to_quote')

    def action_pass_to_file(self):
        self._restagrup_require_stage(('peticion', 'presupuesto'), _('Pasar a expediente'))
        return self._restagrup_gated('pass_to_file', '_restagrup_do_pass_to_file')

    def action_close_file(self):
        self._restagrup_require_stage(('expediente',), _('Cerrar expediente'))
        return self._restagrup_gated('close_file', '_restagrup_do_close_file')

    def _restagrup_do_pass_to_quote(self):
        self._restagrup_move_to('presupuesto')

    def _restagrup_do_pass_to_file(self):
        self._restagrup_move_to('expediente')

    def _restagrup_do_close_file(self):
        self._restagrup_move_to('cerrado')

    # --- leads que ya existían ---

    @api.model
    def _restagrup_backfill_documents(self):
        """Pone los leads anteriores en las fases del flujo y les da número de documento. Se puede repetir sin
        efectos: solo toca lo que aún está en las etapas de serie de Odoo o sin número."""
        leads = self.with_context(active_test=False, tracking_disable=True, mail_notrack=True)
        for position, (xmlid, key) in enumerate(OLD_STAGE_MAP.items(), start=91):
            old = self.env.ref(xmlid, raise_if_not_found=False)
            if old:
                leads.search([('stage_id', '=', old.id)])._restagrup_set_stage_silently(key)
                if old.sequence < 91:  # las de serie quedan al final y plegadas (solo la primera vez)
                    old.sudo().write({'sequence': position, 'fold': True})
        peticion_or_quote = [self._restagrup_stage('peticion').id, self._restagrup_stage('presupuesto').id]
        with_order = leads.search([('stage_id', 'in', peticion_or_quote)]).filtered(
            lambda l: l.sudo().order_ids.filtered(lambda o: o.state in ('sale', 'done')))
        with_order._restagrup_set_stage_silently('expediente')
        sequence = self.env['ir.sequence'].sudo()
        for lead in leads.search([('restagrup_doc_seq', 'in', (0, False))], order='id'):
            lead.restagrup_doc_seq = int(sequence.next_by_code(SEQUENCE_CODE))

    def _restagrup_set_stage_silently(self, key):
        stage = self._restagrup_stage(key)
        if self:
            self.write({'stage_id': stage.id})
