# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

APPROX_REPORT = 'restagrup_restaurants.action_report_approx_options'


class RestagrupPendingMailOption(models.Model):
    """Opción orientativa (restaurante + menú + precio por persona) que acompaña a una petición de datos a la agencia.
    Guarda una copia de lo ofrecido: si el menú cambia después, lo enviado no cambia."""
    _name = 'restagrup.pending.mail.option'
    _description = 'Opción orientativa de una petición de datos'
    _order = 'sequence, price_per_person, id'

    pending_id = fields.Many2one('restagrup.pending.mail', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', string='Restaurante', required=True, ondelete='restrict')
    menu_id = fields.Many2one('restagrup.restaurant.menu', string='Menú guardado', ondelete='set null')
    menu_name = fields.Char(string='Menú', required=True)
    menu_text = fields.Text(string='Contenido del menú')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id, required=True)
    price_per_person = fields.Monetary(string='Precio por persona (IVA incluido)')

    @api.model
    def _vals_from_menu(self, menu, sequence):
        """Copia de lo que se ofrece: precio de VENTA (nunca el coste) y el menú sin su línea de título."""
        text_lines = menu._render_text(with_price=False).splitlines()[1:]
        return {
            'sequence': sequence, 'partner_id': menu.partner_id.id, 'menu_id': menu.id, 'menu_name': menu.name,
            'menu_text': '\n'.join(text_lines), 'currency_id': menu.currency_id.id,
            'price_per_person': menu.sale_price,
        }

    def _title(self, index, show_restaurants):
        self.ensure_one()
        label = self.partner_id.name if show_restaurants else _('Opción %s') % index
        if self.partner_id.city:
            label = '%s (%s)' % (label, self.partner_id.city)
        return label


class RestagrupPendingMail(models.Model):
    _inherit = 'restagrup.pending.mail'

    option_ids = fields.One2many('restagrup.pending.mail.option', 'pending_id', string='Opciones orientativas')
    option_show_restaurants = fields.Boolean(
        string='Mostrar restaurantes', default=True,
        help='Si no se marca, las opciones se presentan como «Opción 1», «Opción 2»… sin el nombre del restaurante.')

    # --- acciones ---

    def action_open_approx_options(self):
        self.ensure_one()
        if self.kind != 'lead_data_request' or self.state != 'pending':
            raise UserError(_('Solo se pueden añadir opciones orientativas a una petición de datos a la agencia'
                              ' que aún no se ha enviado.'))
        wizard = self.env['restagrup.approx.options.wizard']._create_for(self)
        return wizard._reopen()

    def action_clear_approx_options(self):
        for mail in self.filtered(lambda m: m.state == 'pending' and m.option_ids):
            mail.option_ids.unlink()
            mail.body = mail._approx_body()
        return True

    def _set_approx_options(self, menus, show_restaurants):
        """Sustituye las opciones por estos menús (del más barato al más caro) y rehace el texto del correo."""
        self.ensure_one()
        Option = self.env['restagrup.pending.mail.option']
        ordered = menus.sorted(lambda m: (m.sale_price, m.id))
        self.write({
            'option_show_restaurants': show_restaurants,
            'option_ids': [Command.clear()] + [
                Command.create(Option._vals_from_menu(menu, index)) for index, menu in enumerate(ordered, 1)],
        })
        self.body = self._approx_body()
        self.message_post(
            body=Markup('<p>%s</p><ul>%s</ul>') % (
                _('%s ha añadido opciones orientativas al correo:') % self.env.user.name,
                Markup('').join(Markup('<li>%s — %s: %s %s</li>') % (
                    option.partner_id.name, option.menu_name,
                    self.env['restagrup.pricing'].format_amount(option.price_per_person),
                    option.currency_id.symbol or '€')
                    for option in self.option_ids)),
            subtype_xmlid='mail.mt_note',
        )

    # --- texto y adjunto ---

    def _approx_body(self):
        """Texto del correo: lo que falta + (si hay) las opciones orientativas, antes de la firma."""
        self.ensure_one()
        lead = self.request_lead_id
        signer = lead.user_id.name or self.env.company.name
        _subject, body = lead._restagrup_data_request_content(
            lead._restagrup_missing_request_data(), signer, option_lines=self._approx_option_lines())
        return body

    def _approx_option_lines(self):
        if not self.option_ids:
            return []
        pricing = self.env['restagrup.pricing']
        lines = [
            _('Mientras nos lo confirmáis, os adelantamos unas opciones orientativas (precio por persona, IVA incluido;'
              ' sujetas a disponibilidad y a los datos definitivos):'),
        ]
        for index, option in enumerate(self.option_ids, 1):
            lines += ['', '%s. %s — %s: %s %s %s' % (
                index, option._title(index, self.option_show_restaurants), option.menu_name,
                pricing.format_amount(option.price_per_person), option.currency_id.symbol or '€', _('por persona'))]
            lines += ['   %s' % text for text in (option.menu_text or '').splitlines() if text.strip()]
        lines += ['', _('Os adjuntamos estas opciones también en PDF.')]
        return lines

    def _approx_attachments(self):
        """[(nombre, contenido)] con el PDF de opciones orientativas, o [] si el correo no lleva opciones."""
        self.ensure_one()
        if not self.option_ids:
            return []
        content, _kind = self.env['ir.actions.report'].sudo()._render_qweb_pdf(APPROX_REPORT, self.ids)
        name = _('Opciones orientativas - %s.pdf') % (self.request_lead_id.name or '')
        return [(name.replace('/', '-'), content)]
