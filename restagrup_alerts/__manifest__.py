# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Avisos',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Avisos con icono de lo que espera a alguien: pendientes de aprobar, peticiones nuevas, presupuestos por confirmar y elecciones del cliente',
    'description': '''
        Columna discreta de iconos con contador en la esquina de la pantalla. Cada usuario ve los tipos de aviso a
        los que está suscrito (o todos) y, si se activa en Ajustes, lo que es suyo como comercial. Se actualiza en
        tiempo real; al pulsar un icono se abre la lista de lo pendiente.
    ''',
    'author': 'Cositt Technology',
    'depends': ['bus', 'restagrup_agency_proposal'],
    'data': [
        'security/ir.model.access.csv',
        'data/alert_data.xml',
        'views/alert_subscription_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'restagrup_alerts/static/src/css/alerts.css',
            'restagrup_alerts/static/src/js/alerts.js',
            'restagrup_alerts/static/src/js/alerts.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
