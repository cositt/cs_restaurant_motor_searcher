# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Demo 3 guiada (flujo completo)',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Guía de la demo 3: de la petición por correo al expediente cerrado, con pagos y facturas',
    'description': '''
        SOLO PARA LA BASE DE DATOS DE LA DEMO 3 (bd-demo3; no instalar en producción). Pantalla «Guía» con el
        recorrido completo de un grupo y botones que simulan los correos de la agencia y de los restaurantes
        (petición, respuestas, confirmación, justificante de pago, cuenta bancaria y factura), sin servidor de
        correo ni terminal.
    ''',
    'author': 'Cositt Technology',
    'depends': ['restagrup_agency_proposal', 'restagrup_alerts'],
    'external_dependencies': {'python': ['reportlab']},
    'data': [
        'data/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'restagrup_demo3/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
