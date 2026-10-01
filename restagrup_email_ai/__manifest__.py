# -*- coding: utf-8 -*-
{
    'name': 'Restagrup - Email IA',
    'version': '19.0.1.0.0',
    'category': 'Custom',
    'summary': 'Extracción por LLM de los datos de un grupo a partir del email de la agencia',
    'description': '''
        Cuando llega un email de agencia y se crea el lead en el CRM, llama a un LLM
        (mismo patrón de proveedores con fallback que el agente IA original) para
        extraer ciudad, fechas, número de comensales y tipo de grupo, dejando el lead
        listo para revisión humana antes de convertirlo en presupuesto.
    ''',
    'author': 'Cositt Technology',
    'depends': ['crm', 'restagrup_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
