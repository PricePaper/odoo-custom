# -*- coding: utf-8 -*-

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'


    late_order_time = fields.Float(string='Time for Late order')
    lateorder_product_id = fields.Many2one('product.product', string='Late order Fee Product')

ResCompany()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
