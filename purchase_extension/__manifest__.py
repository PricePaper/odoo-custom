# -*- coding: utf-8 -*-

{
    'name': 'Purchase Extension',
    'version': '1.0',
    'category': 'Purchase',
    'summary': "Purchase",
    'description': """
Custom module implemented for Purchase extension.
       """,
    'author': 'Confianz Global',
    'website': 'http://confianzit.com',
    'data': [
        'data/data.xml',
        'views/assets.xml',
        'wizard/view_sale_history_po_views.xml',
        'wizard/cost_discrepancy_report_template.xml',
        'wizard/vendor_product_report_wizard.xml',
        'wizard/discount_check_generate.xml',
        'wizard/update_vendor_pricelist_view.xml',
        'wizard/add_sales_history_to_po.xml',
        'wizard/change_product_uom.xml',
        'views/report_template.xml',
        'views/report_pdf_vendor_product.xml',
        'views/res_company.xml',
        'views/purchase_order_line.xml',
        'views/account_vendor_bill.xml',
        'views/payment_term.xml',
        'views/purchase_order.xml',
        'views/res_partner.xml',
        'views/sale_order.xml',
        'views/product_view.xml',
        'views/purchase_requisition_views.xml',
        'views/purchase_report_template.xml'
    ],
    'depends': ['purchase_requisition', 'stock_orderpoint_enhancements'],
    'installable': True,
    'auto_install': False,
    'application': False,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
