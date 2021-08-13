# -*- coding: utf-8 -*-

from odoo import fields, models, api


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




# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
