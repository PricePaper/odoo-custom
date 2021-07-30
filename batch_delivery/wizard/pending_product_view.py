# -*- coding: utf-8 -*-

from odoo import fields, models, api


class PendingProductView(models.TransientModel):
    _name = 'pending.product.view'
    _description = 'Pending Product View'

    batch_ids = fields.Many2many("stock.picking.batch", string='Batch List')
    picking_ids = fields.Many2many('stock.picking', string='Pick List')
    pending_line_ids = fields.One2many('pending.product.email.view', 'wiz_id', string='Pending List')

    def generate_move_lines(self):
        """
        Extract the pickings from batch and filtered out the pending move lines.
        """
        records = self.batch_ids.mapped('picking_ids') if self.batch_ids else self.picking_ids
        move_lines = records.filtered(lambda pick: pick.state not in ['done', 'cancel']).mapped('move_lines').ids
        action = self.env['ir.actions.act_window'].for_xml_id('batch_delivery', 'stock_move_pending_product_action')
        action['domain'] = [('id', 'in', move_lines)]
        return action

    def generate_mails(self):
        """
        generate emails for individual (sales followers) who having pending product moves.
        """
        recipient_ids = self.pending_line_ids.mapped('followers')
        mail_template = self.env.ref('batch_delivery.email_price_paper_pending_product_mail')
        mail_group = {}
        for rep in recipient_ids:
            for move in self.pending_line_ids:
                if rep in move.followers:
                    mail_group.setdefault(rep, []).append(move)
        for rep, moves in mail_group.items():
            mail_template.with_context({'summery_list': moves, 'partner_email': rep.email}).send_mail(rep.id,
                                                                                                      force_send=True)

    @api.model
    def default_get(self, fields_list):
        res = super(PendingProductView, self).default_get(fields_list)
        if self._context.get('email_wizard'):
            records = self.env['stock.move']
            if self._context.get('default_picking_ids'):
                records = self.env['stock.picking'].browse(self._context.get('default_picking_ids')). \
                    filtered(lambda pick: pick.state not in ['done', 'cancel']). \
                    mapped('move_lines').filtered(lambda l: l.product_uom_qty != l.reserved_availability)
            elif self._context.get('default_batch_ids'):
                records = self.env['stock.picking.batch'].browse(self._context.get('default_batch_ids')). \
                    mapped('picking_ids').filtered(lambda pick: pick.state not in ['done', 'cancel']). \
                    mapped('move_lines').filtered(lambda l: l.product_uom_qty != l.reserved_availability)

            res['pending_line_ids'] = [(0, 0, {
                'product_id': move.product_id.id,
                'product_uom_qty': move.product_uom_qty,
                'reserved_available_qty': move.reserved_availability,
                'product_uom': move.product_uom.id,
                'picking_id': move.picking_id.id,
                'followers': [(6, 0, move.sale_line_id.order_id.message_partner_ids.filtered(lambda u: u.user_ids).ids)],
                'same_product_ids': [(6, 0, move.product_id.same_product_ids.ids)]
            }) for move in records]
        return res


PendingProductView()


class PendingProductLineView(models.TransientModel):
    _name = 'pending.product.email.view'

    product_id = fields.Many2one('product.product', string='Product')
    product_uom_qty = fields.Float(string="Product Quantity")
    reserved_available_qty = fields.Float(string="Available Quantity")
    product_uom = fields.Many2one('uom.uom', string="Product UOM")
    note = fields.Text(string="Note")
    followers = fields.Many2many('res.partner', string="Followers")
    same_product_ids = fields.Many2many('product.product', string="Alternative Products")
    wiz_id = fields.Many2one('pending.product.view')
    picking_id = fields.Many2one('stock.picking', string='Source')


PendingProductLineView()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
