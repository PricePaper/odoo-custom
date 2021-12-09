# -*- coding: utf-8 -*-

from odoo import api, fields, models


class StockBackorderConfirmation(models.TransientModel):
    _inherit = 'stock.backorder.confirmation'



    @api.one
    def _process(self, cancel_backorder=False):
        cancel_backorder = cancel_backorder
        if self._context.get('back_order_cancel', False):
            cancel_backorder = False
        StockReturn = self.env['stock.picking.return']
        for pick_id in self.pick_ids:
            if pick_id.sale_id:
                pick_id.check_return_reason()
                StockReturn.create({
                    'name': 'RETURN-' + pick_id.name,
                    'picking_id': pick_id.id,
                    'sale_id': pick_id.sale_id.id,
                    'sales_person_ids': [
                        (6, 0, pick_id.sale_id and
                         pick_id.sale_id.sales_person_ids and
                         pick_id.sale_id.sales_person_ids.ids)],
                    'return_line_ids': [(0, 0, {
                        'product_id': move.product_id.id,
                        'ordered_qty': move.product_uom_qty,
                        'delivered_qty': move.quantity_done if move.reserved_availability == move.product_uom_qty else move.reserved_availability,
                        'reason_id': move.reason_id.id
                    }) for move in pick_id.move_ids_without_package if move.quantity_done != move.product_uom_qty]
                })

                for move in pick_id.move_ids_without_package:
                    move.sale_line_id.pre_delivered_qty += move.quantity_done
                # if not cancel_backorder:
                #     order = self.env['sale.order.line'].search(
                #         [('order_id', '=', pick_id.sale_id.id), ('is_delivery', '=', True)])
                #     order.write({'product_uom_qty': order.product_uom_qty + 1})
        super(StockBackorderConfirmation, self)._process(cancel_backorder)
        if self._context.get('back_order_cancel', False):
            for pick_id in self.pick_ids:
                backorder_pick = self.env['stock.picking'].search([('backorder_id', '=', pick_id.id)])
                make2order = backorder_pick.move_ids_without_package.filtered(lambda r: r.procure_method == 'make_to_order')
                make2stock = backorder_pick.move_ids_without_package.filtered(lambda r: r.procure_method != 'make_to_order')
                if make2order and make2stock:
                    make2stock.action_cancel_move()
                elif not make2order and make2stock:
                    backorder_pick.action_cancel()



StockBackorderConfirmation()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
