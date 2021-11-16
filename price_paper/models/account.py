# -*- coding: utf-8 -*-

import datetime
from datetime import timedelta, date

from odoo import models, fields, api, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import ValidationError, UserError

MAP_INVOICE_TYPE_PAYMENT_SIGN = {
    'out_invoice': 1,
    'in_refund': -1,
    'in_invoice': -1,
    'out_refund': 1,
}


class AccountPaymentTermLine(models.Model):
    _inherit = "account.payment.term.line"

    grace_period = fields.Integer(help="Gives the number of days extended for the customer after defaulting payments.",
                                  string='Customer Grace Period')


AccountPaymentTermLine()


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    code = fields.Char(string='Code')


AccountFiscalPosition()


class AccountTax(models.Model):
    _inherit = "account.tax"

    code = fields.Char(string='Code')


AccountTax()


class AccountMove(models.Model):
    _inherit = "account.move.line"

    date_maturity_grace = fields.Date(string='Grace period Date')


AccountMove()


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    gross_profit = fields.Monetary(compute='calculate_gross_profit', string='Predicted Profit')
    storage_down_payment = fields.Boolean(copy=False)
    # is_released = fields.Boolean(copy=False)
    discount_from_batch = fields.Float('WriteOff Discount')
    invoice_address_id = fields.Many2one('res.partner', string="Billing Address")

    # def storage_contract_release(self):
    #     sale_order = self.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')
    #     self.write({'is_released': True})
    #     sale_order.run_storage()
    #     sale_order.message_post(body='Sale Order Released by : %s'%self.env.user.name)

    @api.model
    def create(self, vals):
        return super(AccountInvoice, self.with_context(tracking_disable=True)).create(vals)

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner_id(self):
        res = super(AccountInvoice, self)._onchange_partner_id()
        if self.partner_id:
            addr = self.partner_id.address_get(['delivery', 'invoice'])
            self.invoice_address_id = addr['invoice']
        else:
             self.invoice_address_id = False
        return res

    @api.multi
    def invoice_validate(self):
        for invoice in self:
            if not invoice.payment_term_id and invoice.type in ('out_invoice', 'in_invoice'):
                raise ValidationError(_('Payment term is not set for invoice %s' % (invoice.number)))
        res = super(AccountInvoice, self).invoice_validate()
        return res

    @api.model
    def _anglo_saxon_sale_move_lines(self, i_line):
        """override for stock contract.
        passing extra context value to identify the sc stock liability account.
        """
        inv = i_line.invoice_id
        flag = False
        if i_line.is_storage_contract and not inv.storage_down_payment:
            if i_line.sale_line_ids.mapped('order_id').storage_contract:
                flag = True
            else:
                flag = 'sc_order'
        return super(AccountInvoice, self.with_context({'sc_move': flag}))._anglo_saxon_sale_move_lines(i_line)

    @api.multi
    def action_invoice_cancel(self):
        main = self.env['sale.order']
        for sale_order in self.mapped('invoice_line_ids').mapped('sale_line_ids').mapped('order_id'):
            if sale_order.storage_contract and sale_order.state == 'released':
                main |= sale_order
        if main:
            main.write({'state': 'done'})
        return super(AccountInvoice, self).action_invoice_cancel()

    @api.depends('invoice_line_ids.profit_margin')
    def calculate_gross_profit(self):
        """
        Compute the gross profit in invoice.
        """
        for invoice in self:
            gross_profit = 0
            for line in invoice.invoice_line_ids:
                gross_profit += line.profit_margin
            if invoice.partner_id.payment_method == 'credit_card':
                gross_profit -= invoice.amount_total * 0.03
            if invoice.payment_term_id.discount_per > 0:
                gross_profit -= invoice.amount_total * (invoice.payment_term_id.discount_per / 100)
            invoice.update({'gross_profit': round(gross_profit, 2)})

    # @api.multi
    # def finalize_invoice_move_lines(self, move_lines):
    #     """
    #     overriden to set extended the grace period for customer.
    #     """
    #     res = super(AccountInvoice, self).finalize_invoice_move_lines(move_lines)
    #
    #     credit_lines = []
    #     debit_lines = []
    #     debit_lines1 = []
    #     payment_term = self.payment_term_id
    #     if payment_term and isinstance(res, list):
    #         for line in res:
    #             vals = line[2]
    #
    #             # Seperate credit and debit lines. We only need to process debit lines.
    #             if vals.get('credit', False):
    #                 credit_lines.append(vals)
    #             if vals.get('debit', False):
    #                 print('QQ', vals)
    #                 if vals.get('invoice_id', False):
    #                     debit_lines.append(vals)
    #                 else:
    #                     debit_lines1.append(vals)
    #
    #         for line, term in zip(debit_lines, payment_term.line_ids):
    #             if line.get('date_maturity'):
    #                 grace_period_due = str(
    #                     datetime.datetime.strptime(line.get('date_maturity', ''), "%Y-%m-%d").date() + timedelta(
    #                         days=term.grace_period))
    #                 line.update({'date_maturity_grace': grace_period_due})
    #
    #         # Recreate the original list and return
    #         res = [(0, 0, line) for line in credit_lines] + [(0, 0, line) for line in debit_lines] + [(0, 0, line) for line in debit_lines1]
    #     return res


AccountInvoice()


class AccountInvoiceLine(models.Model):
    _inherit = "account.invoice.line"

    profit_margin = fields.Monetary(compute='calculate_profit_margin', string="Profit Margin")
    #comment the below 2 lines while running sale order line import scripts
    lst_price = fields.Float(string='Standard Price', digits=dp.get_precision('Product Price'), store=True,
                             compute='_compute_lst_cost_prices')
    working_cost = fields.Float(string='Working Cost', digits=dp.get_precision('Product Price'), store=True,
                                compute='_compute_lst_cost_prices')
    is_storage_contract = fields.Boolean(compute='_compute_is_storage_contract', store=True)

    @api.depends('sale_line_ids.storage_contract_line_id', 'sale_line_ids.order_id.storage_contract')
    def _compute_is_storage_contract(self):
        for line in self:
            if line.sale_line_ids:
                if len(line.sale_line_ids.mapped('storage_contract_line_id.id')):
                    line.is_storage_contract = True
                elif any(line.sale_line_ids.mapped('order_id.storage_contract')):
                    line.is_storage_contract = True
                else:
                    line.is_storage_contract = False
            elif line.purchase_line_id and line.purchase_line_id.sale_line_id:
                if line.purchase_line_id.sale_line_id.storage_contract_line_id:
                    line.is_storage_contract = True
                elif line.purchase_line_id.sale_line_id.order_id.storage_contract:
                    line.is_storage_contract = True
                else:
                    line.is_storage_contract = False

    # Uncomment the below 2 lines while running sale order line import scripts
    # lst_price = fields.Float(string='Standard Price', digits=dp.get_precision('Product Price'))
    # working_cost = fields.Float(string='Working Cost', digits=dp.get_precision('Product Price'))


    # def _get_anglo_saxon_price_unit(self):
    #     price_unit = super(AccountInvoiceLine,self)._get_anglo_saxon_price_unit()
    #     if self.product_id.invoice_policy == "delivery":
    #         price_unit = self.uom_id._compute_price(price_unit, self.product_id.uom_id)
    #     return price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        domain = {}
        self.uom_id = self.product_id.uom_id
        res = super(AccountInvoiceLine, self)._onchange_product_id()
        domain = res.get('domain', {})
        product_uom_domain = domain.get('uom_id', [])
        product_uom_domain.append(('id', 'in', self.product_id.sale_uoms.ids))
        return res

    @api.depends('product_id', 'uom_id')
    def _compute_lst_cost_prices(self):
        for line in self:
            if line.product_id and line.uom_id:
                uom_price = line.product_id.uom_standard_prices.filtered(lambda r: r.uom_id == line.uom_id)
                if uom_price:
                    line.lst_price = uom_price[0].price
                    if line.product_id.cost:
                        line.working_cost = uom_price[0].cost

    @api.depends('product_id', 'price_unit', 'quantity')
    def calculate_profit_margin(self):
        """
        Calculate profit margin in account invoice
        """
        for line in self:
            if line.product_id and line.product_id.default_code in ['misc'] and not line.sale_line_ids:
                line.profit_margin = 0.0
            elif line.sale_line_ids and line.sale_line_ids.filtered(lambda rec: rec.is_delivery is True):
                line.profit_margin = sum(line.sale_line_ids.mapped('profit_margin'))

            if line.product_id and line.quantity > 0 and line.uom_id:
                if line.product_id == line.invoice_id.company_id.check_bounce_product:
                    line.profit_margin = 0
                    continue
                if line.sale_line_ids and len(line.sale_line_ids) == 1:
                    if line.quantity == line.sale_line_ids.product_uom_qty:
                        line.profit_margin = line.sale_line_ids.profit_margin
                    else:
                        if line.sale_line_ids.product_uom_qty == 0:
                            line.profit_margin = 0
                        else:
                            line.profit_margin = line.sale_line_ids.profit_margin * line.quantity / line.sale_line_ids.product_uom_qty
                    continue
                product_price = line.working_cost
                line_price = line.price_unit
                if line.product_id.uom_id == line.uom_id and line.quantity % 1 != 0.0:
                    numer = line.price_unit * line.quantity
                    denom = (int(line.quantity / 1.0) + (
                                (line.quantity % 1) * (100 + line.product_id.categ_id.repacking_upcharge) / 100))
                    line_price = round(numer / denom, 2)
                line.profit_margin = (line_price - product_price) * line.quantity

    @api.onchange('uom_id')
    def _onchange_uom_id(self):
        res = super(AccountInvoiceLine, self)._onchange_uom_id()
        if self.product_id:
            self._set_taxes()
        return res

    def _set_taxes(self):
        """
        overriden to update the unit price based on the pricelist and
        tax based on resale number and previous sale.
        """
        res = super(AccountInvoiceLine, self)._set_taxes()
        if self.invoice_id.type == 'out_invoice':
            prices_all = self.env['customer.product.price']
            for rec in self.invoice_id.partner_id.customer_pricelist_ids:
                if not rec.pricelist_id.expiry_date or rec.pricelist_id.expiry_date >= str(date.today()):
                    prices_all |= rec.pricelist_id.customer_product_price_ids
            prices_all = prices_all.filtered(
                lambda r: r.product_id.id == self.product_id.id and r.product_uom.id == self.uom_id.id and (
                            not r.partner_id or r.partner_id.id == self.invoice_id.partner_id.id))
            product_price = 0.0
            for price_rec in prices_all:
                if not price_rec.partner_id and prices_all.filtered(lambda r: r.partner_id):
                    continue
                product_price = price_rec.price
                break
            if not product_price:
                if self.uom_id and self.product_id:
                    uom_price = self.product_id.uom_standard_prices.filtered(lambda r: r.uom_id == self.uom_id)
                    if uom_price:
                        product_price = uom_price[0].price
            if self.product_id.uom_id == self.uom_id and self.quantity % 1 != 0.0:
                product_price = ((int(self.quantity / 1) * product_price) + ((self.quantity % 1) * product_price * (
                            (100 + self.product_id.categ_id.repacking_upcharge) / 100))) / self.quantity
            self.price_unit = product_price

            sale_tax_history = self.env['sale.tax.history'].search(
                [('partner_id', '=', self.invoice_id.partner_shipping_id.id), ('product_id', '=', self.product_id.id)],
                limit=1)
            if sale_tax_history and not sale_tax_history.tax:
                self.tax_id = [(5, _, _)]

        return res


AccountInvoiceLine()


class PaymentTerm(models.Model):
    _inherit = 'account.payment.term'

    set_to_default = fields.Boolean(string='Default')


PaymentTerm()


class account_abstract_payment(models.AbstractModel):
    _inherit = "account.abstract.payment"

    @api.depends('invoice_ids', 'amount', 'payment_date', 'currency_id')
    def _compute_payment_difference(self):
        for pay in self.filtered(lambda p: p.invoice_ids):
            payment_amount = -pay.amount if pay.payment_type == 'outbound' else pay.amount
            flag = False
            for inv in pay.invoice_ids:
                days = (inv.date_invoice - fields.Date.context_today(inv)).days
                if abs(days) < inv.payment_term_id.due_days and inv.type in ['out_invoice', 'in_invoice']:
                    flag = True
                    break
                elif inv.discount_from_batch:
                    flag = True
                    break
            currency = pay.currency_id

            pay.payment_difference = pay.with_context(exclude_discount=True)._compute_payment_amount(invoices=pay.invoice_ids, currency=currency) - payment_amount
            if pay.payment_type in ['inbound', 'outbound'] and flag:
                company = self.env.user.company_id
                pay.payment_difference_handling = 'reconcile'
                pay.writeoff_label = ','.join(pay.invoice_ids.mapped('payment_term_id').mapped('name'))
                pay.writeoff_account_id = company.purchase_writeoff_account_id if pay.payment_type == 'outbound' else company.discount_account_id


    # @api.multi
    # def _compute_payment_amount(self, invoices=None, currency=None):
    #     # Get the payment invoices
    #     if not invoices:
    #         invoices = self.mapped('invoice_ids')
    #
    #     # Get the payment currency
    #     payment_currency = currency
    #     if not payment_currency:
    #         payment_currency = self.currency_id or self.journal_id.currency_id or self.journal_id.company_id.currency_id or invoices and \
    #                            invoices[0].currency_id
    #
    #     # Avoid currency rounding issues by summing the amounts according to the company_currency_id before
    #     invoice_datas = invoices.read_group(
    #         [('id', 'in', invoices.ids)],
    #         ['currency_id', 'type', 'residual_signed', 'residual_company_signed'],
    #         ['currency_id', 'type'], lazy=False)
    #
    #     total = 0.0
    #
    #     for invoice_data in invoice_datas:
    #         sign = MAP_INVOICE_TYPE_PAYMENT_SIGN[invoice_data['type']]
    #         amount_total = sign * invoice_data['residual_signed']
    #         amount_total_company_signed = sign * invoice_data['residual_company_signed']
    #         invoice_currency = self.env['res.currency'].browse(invoice_data['currency_id'][0])
    #
    #         if payment_currency == invoice_currency:
    #             total += amount_total
    #         else:
    #             amount_total_company_signed = self.journal_id.company_id.currency_id._convert(
    #                 amount_total_company_signed,
    #                 payment_currency,
    #                 self.env.user.company_id,
    #                 self.payment_date or fields.Date.today()
    #             )
    #             total += amount_total_company_signed
    #
    #     if not self._context.get('exclude_discount', False):
    #         for inv in self.invoice_ids:
    #             days = (inv.date_invoice - fields.Date.context_today(inv)).days
    #             if payment_currency == inv.currency_id:
    #                 invoice_amount = inv.amount_total
    #             else:
    #                 invoice_amount = self.journal_id.company_id.currency_id._convert(
    #                     inv.amount_total,
    #                     payment_currency,
    #                     self.env.user.company_id,
    #                     self.payment_date or fields.Date.today()
    #                 )
    #
    #             if abs(days) < inv.payment_term_id.due_days:
    #                 discount = inv.payment_term_id.discount_per
    #                 if inv.type == 'out_invoice':
    #                     total = total - (invoice_amount * (discount / 100))
    #                 elif inv.type == 'in_invoice':
    #                     total = total + (invoice_amount * (discount / 100))
    #     return total

account_abstract_payment()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
