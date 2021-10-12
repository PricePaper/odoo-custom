# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    show_customer_contract_line = fields.Boolean(compute='_compute_show_contract_line')

    def _compute_show_contract_line(self):
        super(SaleOrder, self)._compute_show_contract_line()
        for order in self:
            if order.partner_id:
                count = self.env['customer.contract.line'].search_count([
                    ('contract_id.expiration_date', '>', fields.Datetime.now()),
                    ('contract_id.partner_ids', 'in', order.partner_id.ids),
                    ('remaining_qty', '>', 0.0),
                    ('state', '=', 'confirmed')
                ])
                order.show_customer_contract_line = bool(count)

    @api.multi
    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        for order in self:
            lines = self.env['customer.contract.line'].search([
                '|', ('contract_id.expiration_date', '<', fields.Datetime.now()),
                ('contract_id.partner_ids', 'in', order.partner_id.ids),
                ('remaining_qty', '<=', 0.0),
                ('state', '=', 'confirmed')
            ])
            lines.mapped('contract_id').action_expire()
        return res


SaleOrder()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    customer_contract_line_id = fields.Many2one('customer.contract.line', string="Customer Contract Applicable")

    @api.onchange('customer_contract_line_id')
    def contract_line_id_change(self):
        if self.customer_contract_line_id:
            self.product_id = self.customer_contract_line_id.product_id
        return {
            'domain': {'customer_contract_line_id': [
                ('contract_id.expiration_date', '>', fields.Datetime.now()),
                ('remaining_qty', '>', 0),
                ('contract_id.partner_ids', 'in', self.order_id.partner_id.ids),
                ('state', '=', 'confirmed')]}
        }

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        result = super(SaleOrderLine, self).product_uom_change()
        if self.customer_contract_line_id:
            self.price_unit = self.customer_contract_line_id.price
            remaining = self.customer_contract_line_id.remaining_qty + self.product_uom_qty
            if self.product_uom_qty > remaining:
                warning_mess = {
                    'title': _('More than Customer Contract'),
                    'message': _(
                        'You are going to Sell more than in customer contract.Only %s is remaining in this contract.' % (
                            self.customer_contract_line_id.remaining_qty + self.product_uom_qty))
                }
                self.product_uom_qty = 0
                result.update({'warning': warning_mess})
        return result


SaleOrderLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
