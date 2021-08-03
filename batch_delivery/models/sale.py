# -*- coding: utf-8 -*-

import json

from odoo import api, fields, models, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    have_prive_lock = fields.Boolean(compute='_compute_price_lock')
    delivery_date = fields.Date(string="Delivery Date")
    batch_processed = fields.Boolean(copy=False)

    @api.depends('order_line.price_lock')
    def _compute_price_lock(self):
        for rec in self:
            rec.have_prive_lock = any(rec.order_line.mapped('price_lock'))

    @api.multi
    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        for sale in self:
            if 'state' not in vals and sale.batch_processed and not self._context.get('recursive_stop'):
                sale.with_context(recursive_stop=True).action_done()
        return res

SaleOrder()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    lot_id = fields.Many2one('stock.production.lot', 'Lot')
    info = fields.Char(compute='_get_price_lock_info_JSON')
    pre_delivered_qty = fields.Float(default=0.00, copy=False)

    @api.one
    @api.depends('product_id')
    def _get_price_lock_info_JSON(self):
        self.info = json.dumps(False)
        if self.product_id and self.price_from and self.price_from.price_lock:
            info = {'title': 'Price locked until ' + self.price_from.lock_expiry_date.strftime('%m/%d/%Y'),
                    'record': self.price_from.id}
            self.info = json.dumps(info)

    @api.onchange('product_id')
    def _onchange_product_id_set_lot_domain(self):
        available_lot_ids = []
        if self.order_id.warehouse_id and self.product_id:
            location = self.order_id.warehouse_id.lot_stock_id
            quants = self.env['stock.quant'].read_group([
                ('product_id', '=', self.product_id.id),
                ('location_id', 'child_of', location.id),
                ('quantity', '>', 0),
                ('lot_id', '!=', False),
            ], ['lot_id'], 'lot_id')
            available_lot_ids = [quant['lot_id'][0] for quant in quants]
        self.lot_id = False
        return {
            'domain': {'lot_id': [('id', 'in', available_lot_ids)]}
        }

    @api.onchange('lot_id')
    def _onchange_product_id_lot_qty_warning(self):
        if self.lot_id and self.lot_id.quant_ids:
            quants = self.lot_id.quant_ids.filtered(lambda q: q.location_id.usage in ['internal'])
            product_qty = sum(quants.mapped('quantity'))

            warning_mess = {
                'title': _('Warning!'),
                'message': _('Please note that there are only %s quantities of %s currently in this lot' % (
                    product_qty, self.product_id.name))
            }
            res = {'warning': warning_mess}
            return res

    @api.multi
    def _prepare_invoice_line(self, qty):
        self.ensure_one()
        result = super(SaleOrderLine, self)._prepare_invoice_line(qty)
        moves = self.mapped('move_ids').filtered(lambda rec: rec.state not in ['cancel'])
        if moves:
            result.update({'stock_move_ids': [(6, 0, moves.ids)]})
        return result


SaleOrderLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
