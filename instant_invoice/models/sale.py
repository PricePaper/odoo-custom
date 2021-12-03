# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import Warning


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    quick_sale = fields.Boolean(string='is_quick_sale', default=False, copy=False)

    @api.multi
    def write(self, vals):
        """
        auto save the delivery line.
        """
        res = super(SaleOrder, self).write(vals)
        for order in self:
            if order.quick_sale:
                order._remove_delivery_line()

    @api.multi
    def action_quick_sale(self):
        for rec in self.sudo():
            if all(line.product_id.type == 'service' for line in rec.order_line):
                raise Warning("You cannot confirm a quick Sales Order with only having Service products.")
            rec.quick_sale = True
            res = rec.action_confirm()
            if res and res != True and res.get('context') and res.get('context').get('warning_message'):
                return res
            picking_ids = rec.picking_ids.filtered(lambda r: r.state not in ('cancel', 'done', 'in_transit'))
            for picking in picking_ids:
                picking.action_make_transit()
                picking.create_invoice()
            # rec.quick_sale = True
        return True

    @api.multi
    def action_print_invoice(self):
        invoice = self.invoice_ids
        invoice.filtered(lambda inv: not inv.sent).write({'sent': True})
        return self.env.ref('instant_invoice.account_invoices_quick_sale').report_action(invoice)

    @api.multi
    def action_print_pick_ticket(self):
        picking = self.picking_ids
        return picking.print_picking_operation()

    @api.multi
    def action_print_product_label(self):
        picking = self.picking_ids
        return picking.print_product_label()

    @api.multi
    def print_quotation(self):
        if self.quick_sale:
            return self.env.ref('instant_invoice.action_report_quick_saleorder') \
                .with_context(discard_logo_check=True).report_action(self)
        return super(SaleOrder, self).print_quotation()

    @api.multi
    def action_release_credit_hold(self):
        """
        release hold sale order for credit limit exceed.
        """
        for order in self:
            order.write({'is_creditexceed': False, 'ready_to_release': True})
            order.message_post(body="Credit Team Approved")
            if order.release_price_hold:
                order.hold_state = 'release'
                if not self.quick_sale:
                    order.action_confirm()
                else:
                    order.action_quick_sale()
            else:
                order.hold_state = 'price_hold'

    @api.multi
    def action_release_price_hold(self):
        """
        release hold sale order for low price.
        """
        for order in self:
            order.write({'is_low_price': False, 'release_price_hold': True})
            order.message_post(body="Sale Team Approved")
            if order.ready_to_release:
                order.hold_state = 'release'
                if not self.quick_sale:
                    order.action_confirm()
                else:
                    order.action_quick_sale()
            else:
                order.hold_state = 'credit_hold'


SaleOrder()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
