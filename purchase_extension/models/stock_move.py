# -*- coding: utf-8 -*-

from odoo import models, api, _


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        res = super(StockMove, self)._prepare_merge_moves_distinct_fields()
        if self._context.get('from_purchase_write'):
            if 'price_unit' in res:
                res.remove('price_unit')
        return res
StockMove()


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _log_activity_get_documents(self, orig_obj_changes, stream_field, stream, sorted_method=False, groupby_method=False):
        res = super(StockPicking, self)._log_activity_get_documents(orig_obj_changes, stream_field, stream, sorted_method=sorted_method, groupby_method=groupby_method)
        result = {}
        if list(orig_obj_changes.keys())[0]._name == 'purchase.order.line' and stream == 'DOWN':
            for picking, moves in res.items():
                if picking[0].state not in ('done', 'cancel'):
                    for move, qty in moves.items():
                        if move.state not in ('done', 'cancel'):
                            move.product_uom_qty = qty[1][0]
                        else:
                            if picking in result:
                                result[picking][move] = qty
                            else:
                                result[picking] = {move: qty}
                else:
                    result[picking] = moves
        return result


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
