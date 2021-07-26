# -*- coding: utf-8 -*-

from odoo import api, fields, models


class StockBackorderConfirmation(models.TransientModel):
    _inherit = 'stock.backorder.confirmation'

    @api.one
    def _process(self, cancel_backorder=False):
        for pick_id in self.pick_ids:
            for move in pick_id.move_ids_without_package:
                if move.is_storage_contract and move.purchase_line_id:
                    pick_id.over_processed = True
                    move.purchase_line_id.order_id.message_post(
                        body='processed less than what was initially planned for the product %s' % move.product_id.display_name)
        super(StockBackorderConfirmation, self)._process(cancel_backorder)


StockBackorderConfirmation()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
