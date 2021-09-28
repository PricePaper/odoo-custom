# -*- coding: utf-8 -*-

{
    'name': 'Account Batch Payment Extension',
    'version': '1.0',
    'category': 'Accounting',
    'description': """
Allows filtering Batch PaymentMoveLines ..
==============================================================================

This module help to filter out the move lines from existing batch payments

""",
    'author': 'Confianz Global',
    'website': 'http://confianzit.com',
    'depends': ['account_batch_payment', 'sales_commission', 'batch_delivery'],
    'data': [
        'data/data.xml',
        'security/ir.model.access.csv',
        'security/account_batch_payment_extension_security.xml',
        'views/assets.xml',
        'views/res_company.xml',
        'views/account_batch_payment.xml',
        'views/returned_check_process.xml'
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
