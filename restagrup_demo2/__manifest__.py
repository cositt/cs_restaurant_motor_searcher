# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Demo 2 guiada',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Guía de la demo 2: petición incompleta, varias opciones al cliente, confirmaciones y bono',
    'description': '''
        SOLO PARA LA BASE DE DATOS DE LA DEMO 2 (bd-demo2; no instalar en producción). Pantalla «Guía» con el
        recorrido y botones que simulan el correo de la agencia (incompleto), su respuesta y las respuestas de
        los restaurantes, sin servidor de correo ni terminal.
    ''',
    'author': 'Cositt Technology',
    'depends': ['restagrup_agency_proposal'],
    'data': [
        'data/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'restagrup_demo2/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
