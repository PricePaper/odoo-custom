# -*- coding: utf-8 -*-
{
    'name': 'Customer Contract',
    'version': '1.0',
    'summary': 'Customer Contract Management',
    'description': """
Customer Contract
=================================
    """,
    'author': 'Confianz Global',
    'website': 'http://confianzit.com',

    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/customer_contract.xml',
        'views/res_partner.xml',
        'views/sale_order.xml',
        'views/menu.xml'
    ],
    'depends': ['sale_management', 'account', 'price_paper'],
    'installable': True,
    'application': False,
    'auto_install': False,

}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
