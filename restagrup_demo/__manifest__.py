# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Demo guiada',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Pantalla de guía para la demo: pasos, simulación del correo y de la respuesta del restaurante',
    'description': '''
        SOLO PARA LA BASE DE DATOS DE DEMO (no instalar en producción). Añade la pantalla "Guía de la demo"
        con los pasos del recorrido, botones para simular la llegada del correo de la agencia y la respuesta
        del restaurante (sin servidor de correo ni terminal) y notas del presentador.
    ''',
    'author': 'Cositt Technology',
    'depends': ['restagrup_agency_proposal'],
    'data': [
        'data/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'restagrup_demo/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
