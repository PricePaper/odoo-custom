# -*- coding: utf-8 -*-

from odoo import fields, models, api
from odoo.tools.float_utils import float_round


class StockPickingReturn(models.Model):
    _name = 'stock.picking.return'
    _description = 'Stock Picking Return'

    name = fields.Char('Name', readonly=True)
    sales_person_ids = fields.Many2many('res.partner', string='Sales Person')
    picking_id = fields.Many2one('stock.picking', string='Picking')
    sale_id = fields.Many2one('sale.order', string='Sale Order')
    return_line_ids = fields.One2many('stock.picking.return.line', 'return_id')

    @api.model
    def create(self, vals):
        record = super(StockPickingReturn, self).create(vals)
        template = self.env.ref('batch_delivery.stock_return_notification_mail')
        email_context = {}
        mail_to = record.sales_person_ids.ids + record.picking_id.message_partner_ids.filtered(lambda r: r.id not in [1, 2]).ids
        if mail_to:
            email_context['partner_to'] = ','.join(map(str, set(mail_to)))
            email_context['return_date'] = fields.Date.today()
            template.with_context(email_context).send_mail(
                record.id, force_send=True, notif_layout="mail.mail_notification_light")
        return record


StockPickingReturn()


class StockPickingReturnLine(models.Model):
    _name = 'stock.picking.return.line'
    _description = 'Stock Picking Return Line'

    product_id = fields.Many2one('product.product', string='Product')
    ordered_qty = fields.Float('Ordered Qty')
    delivered_qty = fields.Float('Delivered Qty')
    returned_qty = fields.Float('Returned Qty', compute='_compute_returned_qty', store=True)
    return_id = fields.Many2one('stock.picking.return')
    reason_id = fields.Many2one('stock.picking.return.reason', string='Reason For Return')

    @api.depends('ordered_qty', 'delivered_qty')
    def _compute_returned_qty(self):
        for rec in self:
            rec.returned_qty = rec.ordered_qty - rec.delivered_qty


StockPickingReturnLine()


class StockPickingReturnReason(models.Model):
    _name = 'stock.picking.return.reason'
    _description = 'Stock Picking Return Reason'

    name = fields.Text(string='Reason')


class ReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    @api.model
    def default_get(self, fields):

        res = super(ReturnPicking, self).default_get(fields)

        move_dest_exists = False
        product_return_moves = []
        picking = self.env['stock.picking'].browse(self.env.context.get('active_id'))
        if picking:
            res.update({'picking_id': picking.id})
            if picking.state != 'done':
                raise UserError(_("You may only return Done pickings."))
            # In case we want to set specific default values (e.g. 'to_refund'), we must fetch the
            # default values for creation.
            line_fields = [f for f in self.env['stock.return.picking.line']._fields.keys()]
            product_return_moves_data_tmpl = self.env['stock.return.picking.line'].default_get(line_fields)
            for move in picking.move_lines:
                if move.state == 'cancel':
                    continue
                if move.scrapped:
                    continue
                if move.move_dest_ids:
                    move_dest_exists = True
                quantity = move.product_qty - sum(move.move_dest_ids.filtered(lambda m: m.state in ['partially_available', 'assigned', 'done']).\
                                                  mapped('move_line_ids').mapped('product_qty'))
                quantity = move.product_id.uom_id._compute_quantity(quantity, move.product_uom, rounding_method='HALF-UP')
                quantity = float_round(quantity, precision_rounding=move.product_uom.rounding)
                product_return_moves_data = dict(product_return_moves_data_tmpl)
                product_return_moves_data.update({
                    'product_id': move.product_id.id,
                    'quantity': quantity,
                    'move_id': move.id,
                    'uom_id': move.product_uom.id,
                })
                product_return_moves.append((0, 0, product_return_moves_data))

            if not product_return_moves:
                raise UserError(_("No products to return (only lines in Done state and not fully returned yet can be returned)."))
            if 'product_return_moves' in fields:
                res.update({'product_return_moves': product_return_moves})
            if 'move_dest_exists' in fields:
                res.update({'move_dest_exists': move_dest_exists})
            if 'parent_location_id' in fields and picking.location_id.usage == 'internal':
                res.update({'parent_location_id': picking.picking_type_id.warehouse_id and picking.picking_type_id.warehouse_id.view_location_id.id or picking.location_id.location_id.id})
            if 'original_location_id' in fields:
                res.update({'original_location_id': picking.location_id.id})
            if 'location_id' in fields:
                location_id = picking.location_id.id
                if picking.picking_type_id.return_picking_type_id.default_location_dest_id.return_location:
                    location_id = picking.picking_type_id.return_picking_type_id.default_location_dest_id.id
                res['location_id'] = location_id
        return res


    def _prepare_move_default_values(self, return_line, new_picking):

        res = {}
        res = super(ReturnPicking, self)._prepare_move_default_values(return_line, new_picking)
        if res:
            res['product_uom'] = return_line.uom_id.id
            res['price_unit'] = -return_line.move_id.price_unit
        return res



# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
