# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PickingFullReturnWizard(models.TransientModel):
    _name = 'picking.full.return.wizard'
    _description = 'Picking full return'

    picking_id = fields.Many2one('stock.picking', string='Picking',
                                 default=lambda self: self.env['stock.picking'].browse(self._context.get('active_id')))
    sale_id = fields.Many2one(related='picking_id.sale_id', readonly=True)

    @api.multi
    def create_full_return(self):
        picking = self.picking_id
        sale = self.sale_id
        picking.check_return_reason()
        StockReturn = self.env['stock.picking.return']
        StockReturn.create({
            'name': 'RETURN-' + picking.name,
            'picking_id': picking.id,
            'sale_id': sale.id,
            'sales_person_ids': [(6, 0, sale.sales_person_ids and sale.sales_person_ids.ids)],
            'return_line_ids': [(0, 0, {
                'product_id': move.product_id.id,
                'ordered_qty': move.product_uom_qty,
                'delivered_qty': 0,
                'reason_id': move.reason_id.id
            }) for move in picking.move_ids_without_package]
        })
        picking.write({'state': 'assigned', 'is_transit': False, 'batch_id': False})
        picking.mapped('move_ids_without_package').write({'is_transit': False})
        picking.mapped('move_line_ids').write({'qty_done': 0})

        for move in picking.move_ids_without_package:
            move.sale_line_id.qty_delivered -= move.reserved_availability
        order = self.env['sale.order.line'].search([('order_id', '=', picking.sale_id.id), ('is_delivery', '=', True)])
        picking.sale_id.action_unlock()
        order.write({'product_uom_qty': order.product_uom_qty + 1})
        picking.sale_id.action_done()
        invoice = picking.sale_id.invoice_ids.filtered(lambda rec: picking in rec.picking_ids)
        invoice.action_cancel()
        #TODO :: Picking Return
        # action = self.env['ir.actions.act_window'].for_xml_id('stock', 'act_stock_return_picking')
        return True


PickingFullReturnWizard()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:

