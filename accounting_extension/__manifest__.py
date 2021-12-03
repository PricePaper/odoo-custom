# -*- coding: utf-8 -*-

{
    'name': 'Accounting Extension',
    'version': '1.1',
    'category': 'Accounting',
    'summary': "Accounting Extension",
    'description': """
Accounting Extension
====================
User can choose invoice against payments

       """,
    'author': 'Confianz Global',
    'website': 'http://www.confianzit.com',
    'images': [],
    'data': [
            "security/ir.model.access.csv",
            "data/data.xml",
            "wizard/add_new_cash_collected_line_wizard.xml",
            "views/payment_term_view.xml",
            "views/account_payment_view.xml",
            "views/res_company_view.xml",
            "views/account_invoice_view.xml",
            "views/stock_picking_batch.xml"
        ],
    'depends': ["l10n_us_check_printing", "account_voucher", 'purchase_extension', 'price_paper', 'batch_delivery', 'account_reports'],
    'installable': True,
    'application': False,
    'qweb': [
        "static/src/xml/account_payment.xml",
    ],
}




# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
