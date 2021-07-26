# -*- coding: utf-8 -*-

from odoo import models, fields, registry, api, _
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, AccessError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    storage_contract_po = fields.Boolean(compute='_compute_storage_contract_po', store=True, string='Storage Contract PO')

    @api.depends('order_line', 'order_line.sale_line_id')
    def _compute_storage_contract_po(self):
        for order in self:
            out = order.order_line.mapped('sale_line_id.order_id.storage_contract')
            if out and all(out):
                order.storage_contract_po = True
            else:
                order.storage_contract_po = False

    @api.multi
    def button_cancel(self):
        result = super(PurchaseOrder, self).button_cancel()
        self.mapped('order_line.sale_order_id').write({'sc_po_done': False})
        return result

    @api.multi
    def button_confirm(self):
        """
        cancel all other RFQ under the same purchase agreement
        """
        self.mapped('order_line.sale_order_id').action_done()
        return super(PurchaseOrder, self).button_confirm()


PurchaseOrder()

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    accounting_difference = fields.Boolean('Discrepancy', copy=False, compute="_discrepancy",
                                           store=True)  # , search="find_discrepancy")

    stock_journal_item = fields.Many2many('account.move.line', string='Stock Journal', compute="_discrepancy")
    invoice_journal_item = fields.Many2many('account.move.line', string='Invoice Journal', compute="_discrepancy")


    def find_discrepancy(self, operator, value):
        line_ids = []
        for line in self.search([('create_date', '>', '2021-05-02'), ('state', 'not in', ['cancel', 'sent', 'draft'])]):
            if line.product_id:
                print(line,'==============>')
                accounts = line.product_id.product_tmpl_id.get_product_accounts()
                sjl = line.move_ids.mapped('account_move_ids').mapped('line_ids').filtered(lambda r: r.account_id.id == accounts['stock_output'].id)
                ijl = line.invoice_lines.mapped('invoice_id').mapped('move_id').mapped('line_ids').filtered(lambda r: r.account_id.id == accounts['stock_output'].id and r.product_id.id == line.product_id.id)
                if round(abs(sum(sjl.mapped('balance')))) != round(abs(sum(ijl.mapped('balance')))):
                    line_ids.append(line.id)
        print(line_ids)
        return [('id', 'in', line_ids)]

    @api.depends('move_ids.account_move_ids.line_ids.balance', 'invoice_lines.invoice_id.move_id.line_ids.balance')
    def _discrepancy(self):
        for line in self:
            line.accounting_difference = False
            line.stock_journal_item = False
            line.invoice_journal_item = False
            if line.product_id and line.state not in ['cancel', 'draft'] and line.create_date > datetime.strptime('2021-07-02', "%Y-%m-%d"):
                if line.sale_order_id and line.sale_order_id.storage_contract:
                    continue
                accounts = line.product_id.product_tmpl_id.get_product_accounts()
                sjl = line.move_ids.mapped('account_move_ids').mapped('line_ids').filtered(lambda r: r.account_id.id == accounts['stock_input'].id)
                ijl = line.invoice_lines.mapped('invoice_id').mapped('move_id').mapped('line_ids').filtered(lambda r: r.account_id.id == accounts['stock_input'].id \
                    and r.product_id.id == line.product_id.id)


                inv_qty = sum(ijl.mapped('quantity'))
                move_balance = 0
                if inv_qty:
                    move_balance = sum(ijl.mapped('balance')) / sum(ijl.mapped('quantity')) * line.product_qty

                if round(abs(sum(sjl.mapped('balance')))) != round(abs(move_balance)):
                    line.accounting_difference = True
                    line.stock_journal_item = sjl
                    line.invoice_journal_item = ijl

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
