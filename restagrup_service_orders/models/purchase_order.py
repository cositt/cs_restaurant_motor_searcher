# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import html2plaintext

RESPONSE_CLASSIFICATION_PROMPT = """\
Eres un asistente que lee la respuesta de un restaurante a una solicitud de servicio para
un grupo. Devuelve SOLO un objeto JSON, sin texto adicional, con estas claves exactas:
"estado" (uno de: "accepted" si acepta el servicio sin condiciones, "rejected" si lo rechaza
o dice que no puede, "needs_info" si pide algún dato que falta o la respuesta está
incompleta, "serious_issue" si hay una queja seria, amenaza de cancelación, disputa de
precio o cualquier cosa que un humano deba mirar ya, "unclear" si no se puede determinar),
"resumen" (string corto, una frase, resumiendo la respuesta en español).
No inventes nada que no esté en el texto."""


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    restagrup_response_state = fields.Selection(
        selection=[
            ('accepted', 'Aceptado'),
            ('rejected', 'Rechazado'),
            ('needs_info', 'Falta información'),
            ('serious_issue', 'Incidencia grave'),
            ('unclear', 'No está claro'),
        ],
        string='Respuesta del restaurante', copy=False,
        help='Clasificación automática por IA de la última respuesta del restaurante a esta'
             ' hoja de servicio. Nunca cambia el estado del pedido ni actúa solo -- solo'
             ' informa, y si es grave, avisa a un humano.',
    )
    restagrup_response_summary = fields.Text(string='Resumen IA de la respuesta', copy=False)

    def message_update(self, msg_dict, update_vals=None):
        res = super().message_update(msg_dict, update_vals=update_vals)
        for order in self:
            summary = order._restagrup_classify_response(msg_dict)
            self.env['restagrup.restaurant.notice']._register_reply(order, msg_dict, summary=summary)
        return res

    def _restagrup_classify_response(self, msg_dict):
        self.ensure_one()
        if self.state not in ('sent', 'purchase'):
            return
        raw_body = msg_dict.get('body') or ''
        text = html2plaintext(raw_body).strip() if raw_body else ''
        if not text:
            return

        connector = self.env['restagrup.llm.connector']
        data, provider, _log = connector.run(
            'sheet_classification', RESPONSE_CLASSIFICATION_PROMPT, text, source=self, label=self.name, review=False)
        if not data:
            return

        valid_states = dict(self._fields['restagrup_response_state'].selection)
        state = data.get('estado') if data.get('estado') in valid_states else 'unclear'
        summary = data.get('resumen') or False
        self.write({
            'restagrup_response_state': state,
            'restagrup_response_summary': summary,
        })
        self.message_post(body=_(
            'Respuesta clasificada por IA (%(provider)s): %(state)s.'
        ) % {'provider': provider, 'state': valid_states[state]})
        if self.restagrup_sale_order_id:
            self.restagrup_sale_order_id._restagrup_log_on_searches(_(
                '%(restaurant)s respondió a la hoja de servicio (%(state)s): %(summary)s'
            ) % {
                'restaurant': self.partner_id.name,
                'state': valid_states[state],
                'summary': summary or _('sin resumen'),
            })

        if state == 'serious_issue':
            self._restagrup_notify_serious_issue(summary)
        return summary

    def _restagrup_notify_serious_issue(self, summary):
        """Línea roja Conchita: incidencia grave -> avisar a un humano y no tocar
        nada más. Nunca se cambia el estado del pedido ni se actúa en automático."""
        self.ensure_one()
        responsible = self.restagrup_sale_order_id.user_id or self.env.user
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_('Incidencia grave con %s -- revisar antes de actuar', self.partner_id.name),
            note=summary or '',
            user_id=responsible.id,
        )

    restagrup_sale_order_id = fields.Many2one(
        'sale.order', string='Presupuesto de origen',
        readonly=True, copy=False, index=True,
        help='Presupuesto de grupo cuya confirmación generó esta hoja de servicio.',
    )
    restagrup_needs_resend = fields.Boolean(
        string='Cambios pendientes de reenviar', compute='_compute_restagrup_needs_resend',
    )

    @api.depends(
        'state', 'order_line.restagrup_sale_line_id.product_uom_qty',
        'order_line.restagrup_sale_line_id.name', 'order_line.product_qty', 'order_line.name',
        'order_line.restagrup_sale_line_id.service_date', 'order_line.restagrup_sale_line_id.service_hour',
        'order_line.restagrup_sale_line_id.product_id', 'order_line.date_planned', 'order_line.product_id',
    )
    def _compute_restagrup_needs_resend(self):
        for po in self:
            if po.state not in ('sent', 'purchase') or not po.restagrup_sale_order_id:
                po.restagrup_needs_resend = False
                continue
            po.restagrup_needs_resend = bool(po._restagrup_changed_lines())

    def _restagrup_changed_lines(self):
        """Líneas de esta hoja de servicio cuyo pedido de origen cambió (comensales, notas, fecha, hora o
        menú) desde que se generó o se reenvió por última vez."""
        self.ensure_one()
        return self.order_line.filtered(lambda line: line._restagrup_changes())

    def action_view_restagrup_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.restagrup_sale_order_id.id,
            'view_mode': 'form',
        }
