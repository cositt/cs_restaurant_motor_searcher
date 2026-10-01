# -*- coding: utf-8 -*-
"""Evaluación MANUAL de la extracción de eventos contra el LLM real (no es un test automático:
necesita red y una clave en Ajustes → Restagrup). Uso, desde odoo-dev-restagrup/:

    docker compose exec -T odoo sh -c 'odoo shell -d bd-restagrup --no-http --db_host=db \
      --db_user=odoo --db_password="$PASSWORD" --addons-path=/mnt/custom-addons,/mnt/extra-addons,\
/usr/lib/python3/dist-packages/odoo/addons' < custom-addons/restagrup_email_ai/eval/eval_extraction.py

Hoy se fija a 2026-10-01 para que el resultado sea reproducible. Imprime aciertos por campo."""
from odoo.addons.restagrup_email_ai.models.crm_lead import EXTRACTION_SYSTEM_PROMPT

TODAY = '2026-10-01'
# (nombre, texto, eventos esperados [(ciudad, fecha, tipo, pax)])
CASES = [
    ('ES · 3 eventos, 2 ciudades',
     'Buenos días, somos Viajes Sol. Grupo corporativo de 42 personas. Necesitamos comida el 15 de noviembre '
     'en Málaga, cena ese mismo día también en Málaga, y cena el 16 de noviembre en Sevilla. '
     'Hay una persona celíaca. Gracias.',
     [('Málaga', '2026-11-15', 'comida', 42), ('Málaga', '2026-11-15', 'cena', 42), ('Sevilla', '2026-11-16', 'cena', 42)]),
    ('ES · 1 evento con año',
     'Solicitud: comida para 30 estudiantes en Toledo el 3 de diciembre de 2026.',
     [('Toledo', '2026-12-03', 'comida', 30)]),
    ('EN · 3 eventos, año 2027',
     'Hi, we are planning a trip for 25 guests. We would need lunch in Madrid on 10 March 2027, dinner in Madrid '
     'the same day, and lunch in Toledo on 11 March 2027. Please send a quote.',
     [('Madrid', '2027-03-10', 'comida', 25), ('Madrid', '2027-03-10', 'cena', 25), ('Toledo', '2027-03-11', 'comida', 25)]),
    ('ES · año omitido (ya pasó este año)',
     'Hola, queremos una cena para 18 personas el 5 de septiembre en Granada.',
     [('Granada', '2027-09-05', 'cena', 18)]),
    ('ES · sin fecha ni tipo',
     'Buenas, queremos presupuesto para un grupo de 50 personas en Sevilla, ¿qué podéis ofrecer?',
     [('Sevilla', None, None, 50)]),
    ('ES · coffee break + aperitivo',
     'Para el congreso del 20 de enero de 2027 en Valencia necesitamos coffee break por la mañana para 120 '
     'personas y un aperitivo a mediodía para 120.',
     [('Valencia', '2027-01-20', 'coffee_break', 120), ('Valencia', '2027-01-20', 'aperitivo', 120)]),
    ('No es una petición (aviso automático)',
     'Alerta de seguridad: se ha iniciado sesión en tu cuenta desde un dispositivo nuevo. Si no has sido tú, '
     'cambia tu contraseña.',
     []),
    ('ES · adultos + niños',
     'Somos un grupo de 20 adultos y 5 niños, cena el 12 de diciembre de 2026 en Cádiz.',
     [('Cádiz', '2026-12-12', 'cena', (20, 25))]),
    ('ES · fecha dd/mm/aaaa',
     'Almuerzo el 03/04/2027 en Bilbao para 60 pax.',
     [('Bilbao', '2027-04-03', 'comida', 60)]),
]

TYPE_BY_XMLID = {
    'restagrup_core.event_type_breakfast': 'desayuno', 'restagrup_core.event_type_aperitif': 'aperitivo',
    'restagrup_core.event_type_lunch': 'comida', 'restagrup_core.event_type_dinner': 'cena',
    'restagrup_core.event_type_coffee_break': 'coffee_break', 'restagrup_core.event_type_other': 'otro',
}

lead_model = env['crm.lead']
connector = env['restagrup.llm.connector']
prompt = EXTRACTION_SYSTEM_PROMPT.replace('{hoy}', TODAY)
type_name = {env.ref(x).id: k for x, k in TYPE_BY_XMLID.items()}

checked = passed = 0
print('=' * 70)
for name, text, expected in CASES:
    data, provider = connector.extract_json(prompt, text)
    if data is None:
        print('✗ %s -> SIN RESPUESTA DEL LLM (¿clave cargada?)' % name)
        continue
    got = [(v['city'] or None, str(v['event_date']) if v['event_date'] else None,
            type_name.get(v['event_type_id']), v['pax'] or None) for v in lead_model._restagrup_event_vals_list(data)]
    ok_count = len(got) == len(expected)
    checked += 1; passed += ok_count
    print('%s %s  [%s]  eventos: esperados %d, obtenidos %d' % ('✓' if ok_count else '✗', name, provider, len(expected), len(got)))
    for i, exp in enumerate(expected):
        row = got[i] if i < len(got) else (None, None, None, None)
        for label, e, g in zip(('ciudad', 'fecha', 'tipo', 'pax'), exp, row):
            ok = (g in e) if isinstance(e, tuple) else (str(g or '').lower() == str(e or '').lower())
            checked += 1; passed += ok
            if not ok:
                print('     ✗ evento %d %s: esperado %r, obtenido %r' % (i + 1, label, e, g))
print('=' * 70)
print('ACIERTOS: %d/%d (%.0f %%)' % (passed, checked, 100.0 * passed / max(checked, 1)))
