# -*- coding: utf-8 -*-

from odoo import models, fields, api

class ProductTemplate(models.Model):
    _name = 'product.location.change'

    product_id = fields.Many2one('product.product', string='Product')
    source_location_id = fields.Many2one(
        'stock.location', "Source Location", copy=False)
    dest_location_id = fields.Many2one(
        'stock.location', "Destination Location")
    is_done = fields.Boolean('Done', default=False, copy=False)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.source_location_id = self.product_id.property_stock_location
        else:
            self.source_location_id = False


    @api.multi
    def action_change(self):
        for rec in self:
            stock_moves = rec.product_id.stock_move_ids.filtered(lambda r: r.state not in ('done', 'cancel') and r.location_id == rec.source_location_id)
            reserve_qty_dict = {}
            for move in stock_moves:
                if move.reserved_availability > 0:
                    reserve_qty_dict[move] = move.reserved_availability
                    move._do_unreserve()
                move.location_id = rec.dest_location_id.id
            rec.product_id.property_stock_location = rec.dest_location_id.id
            vals = {'is_locked': True,
                'picking_type_id': 5,
                'is_internal_transfer': True,
                'location_id': rec.source_location_id.id,
                'location_dest_id': rec.dest_location_id.id,
                'move_type': 'direct',
                'company_id': 1,
                'partner_id': False,
                'origin': False,
                'owner_id': False,
                'move_ids_without_package': [[0, 0,
                        {'state': 'draft',
                         'picking_type_id': 5,
                         'additional': False,
                         'name': rec.product_id.name,
                         'product_id': rec.product_id.id,
                         'location_id': rec.source_location_id.id,
                         'location_dest_id': rec.dest_location_id.id,
                         'product_uom': rec.product_id.uom_id.id}]],
                }
            internal_transfer = self.env['stock.picking'].create(vals)
            transfer_move = internal_transfer.move_ids_without_package
            transfer_move.product_uom_qty = transfer_move.qty_to_transfer
            internal_transfer.action_confirm()
            internal_transfer.action_assign()
            transfer_move.move_line_ids.qty_done =  transfer_move.product_uom_qty
            internal_transfer.button_validate()
            for to_do_move, qty in reserve_qty_dict.items():
                to_do_move.qty_update = qty
                to_do_move._action_assign_reset_qty()
                if to_do_move.is_transit:
                    move.quantity_done = move.reserved_availability
        return True




ProductTemplate()
