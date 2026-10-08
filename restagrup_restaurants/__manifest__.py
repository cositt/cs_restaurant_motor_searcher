# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Restaurantes',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Ficha de restaurante y buscador (aforo, parking, Google Places, ranking)',
    'description': '''
        Extiende Contactos con los campos de restaurante (aforo, parking de autobús,
        día de cierre, idioma, cuenta bancaria, contacto directo) y añade el buscador
        de restaurantes por zona, vinculado al grupo/cliente (crm.lead) que lo necesita,
        que combina partners propios con resultados de Google Places, con ranking
        determinista (partners primero, luego rating de Google) y tarjetas con todos
        los datos del restaurante (aforo, cocina, precio, parking, apto para...).
    ''',
    'author': 'Cositt Technology',
    'depends': ['mail', 'contacts', 'crm', 'restagrup_core', 'restagrup_email_ai', 'base_geolocalize'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/restaurant_menu_views.xml',
        'views/restaurant_search_views.xml',
        'views/crm_lead_views.xml',
        'views/pending_mail_views.xml',
        'views/inbox_mail_views.xml',
        'views/ai_log_views.xml',
        'data/restaurant_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'restagrup_restaurants/static/src/css/restaurant_search_kanban.css',
            'restagrup_restaurants/static/lib/leaflet/leaflet.css',
            'restagrup_restaurants/static/lib/leaflet/leaflet.js',
            'restagrup_restaurants/static/src/css/restaurant_map.css',
            'restagrup_restaurants/static/src/js/restaurant_map_action.js',
            'restagrup_restaurants/static/src/js/restaurant_map_action.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
