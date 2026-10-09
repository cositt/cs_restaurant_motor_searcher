# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Propuesta a agencias',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'PDF de propuesta de restaurantes para la agencia, con link de portal',
    'description': '''
        Wizard para elegir una búsqueda de restaurantes y generar una propuesta en
        PDF (informe QWeb) enviable a la agencia, con un link de portal para que la
        vean sin necesidad de cuenta interna.
    ''',
    'author': 'Cositt Technology',
    'depends': ['sale_management', 'portal', 'restagrup_service_orders'],
    'data': [
        'security/ir.model.access.csv',
        'reports/restaurant_proposal_report.xml',
        'reports/client_comparison_report.xml',
        'reports/booking_documents.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/payment_views.xml',
        'views/client_comparison_wizard_views.xml',
        'views/portal_templates.xml',
        'views/restaurant_search_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
