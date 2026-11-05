# -*- coding: utf-8 -*-
"""Localizador del grupo en los correos (PPT de Conchita 2026-11-04, diapositiva 4). Las plantillas son noupdate
(lo que edita el equipo no se pisa): solo se cambia el asunto de la petición de presupuesto si sigue siendo el de
partida, y se añade el marcador {localizador} a la lista de marcadores."""

OLD_QUOTE_SUBJECT = 'Consulta de disponibilidad — {fecha} {servicio}, {pax} pax'
NEW_QUOTE_SUBJECT = 'Presupuesto para grupos — {localizador} — {ciudad} {fecha}'
LOCATOR_CODES = ('quote_request', 'quote_reminder', 'quote_incomplete')


def migrate(cr, version):
    cr.execute("""
        UPDATE restagrup_mail_template SET subject = %s WHERE code = 'quote_request' AND subject = %s
    """, (NEW_QUOTE_SUBJECT, OLD_QUOTE_SUBJECT))
    cr.execute("""
        UPDATE restagrup_mail_template SET placeholders = placeholders || ' {localizador}'
         WHERE code IN %s AND placeholders IS NOT NULL AND placeholders NOT LIKE '%%{localizador}%%'
    """, (LOCATOR_CODES,))
