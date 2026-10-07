# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Core',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Configuración y utilidades compartidas por los módulos Restagrup',
    'description': '''
        Base común de los módulos Restagrup: parámetros de configuración
        (claves de API Google Places / proveedores LLM) y utilidades compartidas.
        No aporta funcionalidad visible por sí solo.
    ''',
    'author': 'Cositt Technology',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/event_type_data.xml',
        'data/cancel_reason_data.xml',
        'views/res_config_settings_views.xml',
        'views/event_type_views.xml',
        'views/cancel_reason_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
