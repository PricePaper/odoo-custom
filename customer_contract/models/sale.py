# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from datetime import datetime


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
            self.product_uom = self.customer_contract_line_id.product_id.uom_id
            self.price_unit = self.customer_contract_line_id.price
        else:
            msg, product_price, price_from = super(SaleOrderLine, self).calculate_customer_price()
            self.price_unit = product_price
        return {
            'domain': {'customer_contract_line_id': [
                ('contract_id.expiration_date', '>', fields.Datetime.now()),
                ('remaining_qty', '>', 0),
                ('contract_id.partner_ids', 'in', self.order_id.partner_id.ids),
                ('state', '=', 'confirmed')]}
        }


    @api.multi
    def calculate_customer_contract(self):
        """
        Calculate the unit price of product by
        checking if the product included in any of the
        contracts of selected partner.
        """
        unit_price = 0
        contract_id = False
        for record in self:
            contract_ids = record.order_partner_id.customer_contract_ids.filtered(
                lambda rec: rec.expiration_date > datetime.now())
            for contract in contract_ids:
                contract_product_cost_id = contract.product_line_ids.filtered(
                    lambda rec: rec.product_id.id == record.product_id.id and rec.remaining_qty > 0)
                if contract_product_cost_id:
                    unit_price = contract_product_cost_id.price
                    contract_id = contract_product_cost_id.id
                    break
        return unit_price, contract_id

    @api.onchange('product_id')
    def product_id_change(self):
        """
        Set the unit price of product
        as per the contracts of selected partner
        """
        res = super(SaleOrderLine, self).product_id_change()
        if self.product_id:
            unit_price, contract_id = self.calculate_customer_contract()
            if unit_price:
                res.update({'value': {'price_unit': unit_price, 'customer_contract_line_id': contract_id}})
        return res

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
