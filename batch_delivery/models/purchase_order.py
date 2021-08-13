# -*- coding: utf-8 -*-

from odoo import models, api


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.multi
    def _get_stock_move_price_unit(self):
        self.ensure_one()
        price_unit =  super(PurchaseOrderLine, self)._get_stock_move_price_unit()
        line = self[0]
        if line.product_uom.id != line.product_id.uom_id.id:
            price_unit *=  line.product_id.uom_id.factor / line.product_uom.factor
        return price_unit


PurchaseOrderLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
