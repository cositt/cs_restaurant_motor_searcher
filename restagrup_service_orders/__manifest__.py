# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Pedidos de servicio',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Hoja de servicio por restaurante al confirmar el presupuesto, y aviso de cambios',
    'description': '''
        Al confirmar un presupuesto (sale.order), agrupa las líneas por restaurante y
        genera un pedido de compra (purchase.order) por cada uno -- la "hoja de
        servicio" -- con envío conjunto a todos los restaurantes con un clic.
        Detecta cambios posteriores (comensales, notas) y permite regenerar y
        reenviar solo a los restaurantes afectados, dejando registro de qué cambió.
    ''',
    'author': 'Cositt Technology',
    'depends': ['sale_management', 'purchase', 'restagrup_restaurants', 'restagrup_core'],
    'data': [
        'data/product_data.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/restaurant_search_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
