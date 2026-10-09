# -*- coding: utf-8 -*-
"""A7: «Reenviar cambios» con resumen de qué cambió y confirmación cuando el cambio es significativo."""
from markupsafe import Markup

from odoo import _, models

DEFAULT_CHANGE_CONFIRM_PCT = 20.0
CONFIRM_KINDS = ('date', 'hour')  # un cambio de fecha u hora siempre pide confirmación


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _restagrup_change_confirm_pct(self):
        value = self.env['ir.config_parameter'].sudo().get_param('restagrup.change_confirm_pct')
        try:
            return float(value) if value else DEFAULT_CHANGE_CONFIRM_PCT
        except ValueError:
            return DEFAULT_CHANGE_CONFIRM_PCT

    def _restagrup_is_significant(self, po_lines):
        """¿Alguna de estas líneas de hoja cambió de fecha u hora, o de comensales por encima del umbral?
        Se mira antes de aplicar el cambio, cuando la línea aún lleva los valores que se enviaron."""
        threshold = self._restagrup_change_confirm_pct()
        for line in po_lines:
            for kind, _text in line._restagrup_changes():
                if kind in CONFIRM_KINDS:
                    return True
                if kind == 'pax':
                    old, new = line.product_qty, line.restagrup_sale_line_id.product_uom_qty
                    if not old or abs(new - old) / old * 100 > threshold:
                        return True
        return False

    def _restagrup_apply_changes_to_sheet(self, po):
        """Pasa a la hoja de servicio lo que cambió en el presupuesto y devuelve los textos del cambio."""
        texts = []
        for line in po._restagrup_changed_lines():
            texts += line._restagrup_change_texts()
            sale_line = line.restagrup_sale_line_id
            vals = {
                'product_qty': sale_line.product_uom_qty,
                'name': sale_line.name,
                'date_planned': self._restagrup_planned_datetime(sale_line) or line.date_planned,
            }
            if sale_line.product_id != line.product_id:
                vals.update(product_id=sale_line.product_id.id, price_unit=self._restagrup_restaurant_cost(sale_line))
            line.write(vals)
        return texts

    @staticmethod
    def _restagrup_summary_html(intro, texts, footer=''):
        items = Markup('').join(Markup('<li>%s</li>') % text for text in texts)
        return Markup('<p>%s</p><ul>%s</ul>%s') % (intro, items, Markup(footer))

    def _restagrup_send_with_summary(self, template, record, summary_html):
        """Envía la plantilla de correo de `record` con el resumen del cambio delante del texto habitual."""
        if not template:
            return
        body = template._render_field('body_html', [record.id])[record.id]
        template.sudo().send_mail(
            record.id, force_send=True, email_values={'body_html': Markup('%s%s') % (summary_html, Markup(body))},
        )

    def _restagrup_agency_summary(self, agency_changes):
        if not agency_changes:
            return Markup('')
        items = [Markup('<strong>%s</strong>: %s') % (restaurant, ' · '.join(texts))
                 for restaurant, texts in agency_changes]
        return self._restagrup_summary_html(_('Hemos actualizado el presupuesto. Cambios por restaurante:'), items)

    def _fw_review_restaurant_notice(self):
        sheets = self.sudo().restaurant_po_ids.filtered('restagrup_needs_resend')
        if not sheets:
            return False
        recipients = '\n'.join('• %s <%s>' % (po.partner_id.name, (po.partner_id.email or '').strip() or '—')
                               for po in sheets)
        return _('Se reenviarán los cambios (y la hoja de servicio actualizada) a:\n%s\n\n'
                 'Después se avisará también a la agencia con la proforma.') % recipients

    def action_resend_restaurant_orders(self):
        """Botón «Reenviar cambios»: antes de escribir a los restaurantes, una persona revisa a quién y qué."""
        if len(self) == 1:
            return self._restagrup_gated('notify_restaurant', '_restagrup_do_resend_restaurant_orders')
        return self._restagrup_do_resend_restaurant_orders()

    def _restagrup_do_resend_restaurant_orders(self):
        """Botón «Reenviar cambios»: solo toca las hojas de servicio con cambios pendientes, las actualiza,
        deja constancia en el chatter y reenvía el correo -- con el resumen de qué cambió -- únicamente a los
        restaurantes afectados. Si el cambio es significativo, la hoja vuelve a «pendiente de confirmar» y el
        correo pide la confirmación. Después avisa también a la agencia."""
        template = self.env.ref('purchase.email_template_edi_purchase', raise_if_not_found=False)
        for order in self:
            order._sync_restaurant_purchase_orders()
            agency_changes = []
            for po in order.sudo().restaurant_po_ids.filtered('restagrup_needs_resend'):
                significant = order._restagrup_is_significant(po._restagrup_changed_lines())
                texts = order._restagrup_apply_changes_to_sheet(po)
                if significant:
                    po.write({'restagrup_response_state': False, 'restagrup_response_summary': False})
                if texts:
                    po.message_post(body=order._restagrup_summary_html(
                        _('Cambios detectados en el presupuesto, reenviado al restaurante:'), texts))
                footer = ''
                if significant:
                    footer = '<p><strong>%s</strong></p>' % _(
                        'Necesitamos que confirméis estos cambios respondiendo a este correo.')
                order._restagrup_send_with_summary(
                    template, po, order._restagrup_summary_html(_('Cambios en el servicio:'), texts, footer))
                agency_changes.append((po.partner_id.name, texts))
                order._restagrup_log_on_searches(_('Cambios reenviados a %(restaurant)s: %(changes)s') % {
                    'restaurant': po.partner_id.name,
                    'changes': '; '.join(texts) or _('sin cambios de cantidad'),
                })
            if agency_changes:
                order._restagrup_send_updated_proforma(agency_changes)
