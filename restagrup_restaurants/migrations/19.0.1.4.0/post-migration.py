# -*- coding: utf-8 -*-
"""Ronda de ajustes 09/11: el correo que pide los datos que faltan pasa al texto de Conchita (la plantilla es
noupdate). Solo si nadie la había cambiado: un texto ya editado a mano se respeta."""
from odoo import SUPERUSER_ID, api

OLD_START = 'Buenos días,\n\nPara poder proponeros grupos nos faltan estos datos de {restaurante}:'
NEW_BODY = (
    'Hola {restaurante},\n\n'
    'Para poder contar con vosotros en las próximas solicitudes de grupos, nos faltaría completar vuestra ficha '
    'con estos datos:\n\n{faltan}\n\n'
    '¡Muchas gracias por vuestra colaboración!\nUn saludo,\nEquipo RestaGrup'
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref('restagrup_restaurants.mail_template_data_request', raise_if_not_found=False)
    if template and (template.body or '').startswith(OLD_START):
        template.body = NEW_BODY
