# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from dateutil.relativedelta import relativedelta
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, float_is_zero
from datetime import datetime

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.multi
    def remove_move_reconcile(self):
        discount_lines = self.env['account.move.line']
        for account_move_line in self:
            invoice_id = self._context.get('invoice_id')
            payment = account_move_line.payment_id
            if payment.discount_journal_id:
                discount_lines |= payment.discount_journal_id.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
            else:
                payment_line = account_move_line.payment_id.payment_lines.filtered(lambda r: r.invoice_id.id == invoice_id)
                discount_lines |= payment_line.discount_journal_id.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
        res = super(AccountMoveLine, (self | discount_lines)).remove_move_reconcile()
        discount_lines.mapped('move_id').button_cancel()
        discount_lines.mapped('move_id').unlink()
        return res

    @api.multi
    def remove_active_discount(self, invoice_id=False):
        for account_move_line in self:
            discount_lines = self.env['account.move.line']
            if account_move_line.payment_id and account_move_line.payment_id.discount_journal_id:
                discount_journal = account_move_line.payment_id.discount_journal_id
                discount_lines |= discount_journal.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
            elif account_move_line.payment_id and self._context.get('rec'):
                invoice_id = self._context.get('rec')
                payment_line = account_move_line.payment_id.payment_lines.filtered(lambda r: r.invoice_id.id == invoice_id)
                discount_lines |= payment_line.discount_journal_id.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
            elif invoice_id:
                payment_line = account_move_line.payment_id.payment_lines.filtered(lambda r: r.invoice_id.id == invoice_id)
                discount_lines |= payment_line.discount_journal_id.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
            discount_lines |= account_move_line
            discount_lines.remove_move_reconcile()
            discount_lines.mapped('move_id').button_cancel()
            discount_lines.mapped('move_id').unlink()
        return True


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    discount_date = fields.Date('Discount Till')

    @api.model
    def _get_payments_vals(self):
        if not self.payment_move_line_ids:
            return []
        payment_vals = []
        currency_id = self.currency_id
        for payment in self.payment_move_line_ids:
            payment_currency_id = False
            if self.type in ('out_invoice', 'in_refund'):
                amount = sum([p.amount for p in payment.matched_debit_ids if p.debit_move_id in self.move_id.line_ids])
                amount_currency = sum(
                    [p.amount_currency for p in payment.matched_debit_ids if p.debit_move_id in self.move_id.line_ids])
                if payment.matched_debit_ids:
                    payment_currency_id = all([p.currency_id == payment.matched_debit_ids[0].currency_id for p in
                                               payment.matched_debit_ids]) and payment.matched_debit_ids[
                                              0].currency_id or False
            elif self.type in ('in_invoice', 'out_refund'):
                amount = sum(
                    [p.amount for p in payment.matched_credit_ids if p.credit_move_id in self.move_id.line_ids])
                amount_currency = sum([p.amount_currency for p in payment.matched_credit_ids if
                                       p.credit_move_id in self.move_id.line_ids])
                if payment.matched_credit_ids:
                    payment_currency_id = all([p.currency_id == payment.matched_credit_ids[0].currency_id for p in
                                               payment.matched_credit_ids]) and payment.matched_credit_ids[
                                              0].currency_id or False
            # get the payment value in invoice currency
            if payment_currency_id and payment_currency_id == self.currency_id:
                amount_to_show = amount_currency
            else:
                currency = payment.company_id.currency_id
                amount_to_show = currency._convert(amount, self.currency_id, payment.company_id,
                                                   payment.date or fields.Date.today())
            if float_is_zero(amount_to_show, precision_rounding=self.currency_id.rounding):
                continue
            payment_ref = payment.move_id.name
            invoice_view_id = None
            if payment.move_id.ref:
                payment_ref += ' (' + payment.move_id.ref + ')'
            if payment.invoice_id:
                invoice_view_id = payment.invoice_id.get_formview_id()
            payment_vals.append({
                'name': payment.name,
                'journal_name': payment.journal_id.name,
                'amount': amount_to_show,
                'currency': currency_id.symbol,
                'digits': [69, currency_id.decimal_places],
                'position': currency_id.position,
                'date': payment.date,
                'payment_id': payment.id,
                'account_payment_id': payment.payment_id.id,
                'payment_name': payment.payment_id.name,
                'invoice_id': payment.invoice_id.id,
                'invoice_view_id': invoice_view_id,
                'move_id': payment.move_id.id,
                'ref': payment_ref,
                'is_discount': True if not payment.payment_id and payment.name == 'Discount' else False
            })

        return payment_vals


    @api.multi
    def invoice_validate(self):
        res = super(AccountInvoice, self).invoice_validate()
        if self.payment_term_id and self.payment_term_id.is_discount:
            invoice_date = self.date_invoice
            self.discount_date = invoice_date + relativedelta(days=self.payment_term_id.due_days)
        return res

    @api.multi
    def action_cancel_draft(self):
        self.ensure_one()
        res = super(AccountInvoice, self).action_cancel_draft()
        vals = {'discount_date': False}
        if self.move_name:
            vals.update({'number': self.move_name})
        self.write(vals)
        return res

    def action_invoice_draft(self):
        self.ensure_one()
        res = super(AccountInvoice, self).action_invoice_draft()
        if self.move_name:
            self.write({'number': self.move_name})
        return res

    @api.multi
    def action_cancel_old(self):
        res = super(AccountInvoice, self).action_cancel()
        self.write({'move_name': False})
        return res

    def update_journal(self, offset=0, limit=10000):        
        for aml in self.env['account.move.line'].search([('account_id', '=', 6), ('journal_id', '=', 6), ('debit', '>', 0)], offset=offset, limit=limit):
            if aml.move_id.stock_move_id:
                invoice_line =  self.env['account.invoice.line'].search([('stock_move_ids', 'in', aml.move_id.stock_move_id.id)])
                if not invoice_line:
                    pick = self.env['stock.picking'].search([('name', '=', aml.move_id.ref)])
                    invoice_line = pick.sale_id.invoice_ids.filtered(lambda rec: rec.state not in ('cancel', 'draft')).mapped('invoice_line_ids').filtered(lambda r: r.product_id.id == aml.product_id.id)
                for line in invoice_line:
                    invoice = line.mapped('invoice_id')
                    move = invoice.move_id
                    i=0
                    for c_aml in move.line_ids.filtered(lambda rec: rec.product_id.id == line.product_id.id and rec.product_id is not False and rec.account_id.id == 6):
                        i += 1                        
                        if c_aml.account_id.id == aml.account_id.id and c_aml.credit != aml.debit and aml.debit != 0 and c_aml.credit > 0:
                            cogs = move.line_ids.filtered(lambda rec: rec.product_id.id == line.product_id.id and rec.product_id is not False and rec.account_id.id == 725 and rec.debit == c_aml.credit and rec.debit > 0)
                            if len(cogs) > 1:
                                cogs = cogs[0]
                            if cogs:
                                # print(aml.debit,c_aml.debit,c_aml.credit,cogs.debit, cogs, aml,c_aml)
                                # print("update account_move_line set balance=%s,credit_cash_basis=%s,balance_cash_basis=%s,credit=%s where id=%s" % (aml.debit * -1, aml.debit, aml.debit * -1, aml.debit, c_aml.id))
                                # print("update account_move_line set debit_cash_basis=%s,balance_cash_basis=%s,balance=%s,debit=%s where id=%s" % (aml.debit, aml.debit, aml.debit, aml.debit, cogs.id))
                                self.env.cr.execute("update account_move_line set balance=%s,credit_cash_basis=%s,balance_cash_basis=%s,credit=%s where id=%s", (aml.debit * -1, aml.debit, aml.debit * -1, aml.debit, c_aml.id))
                                self.env.cr.execute("update account_move_line set debit_cash_basis=%s,balance_cash_basis=%s,balance=%s,debit=%s where id=%s", (aml.debit, aml.debit, aml.debit, aml.debit, cogs.id))                                
                                self.env.cr.commit() 
                                # print(aml.debit,c_aml.credit,cogs.debit, cogs, aml,c_aml)
                                # # if input('sssssssss') == 'y':print(o)
                            else:
                                a = open('journal_balance.csv', 'a+')
                                a.write("%s,%s,%s,'no cogs to correct'\n" % (aml.name, c_aml.name, move.name))
                                a.close()        
                                # print('cogs not found', aml, c_aml)  
                            # if c_aml.date != aml.date:
                            #     print("\t\t\tupdate account_move_line set date='%s' where id=%s"% (c_aml.date, aml.id))
                            #     self.env.cr.execute("update account_move_line set date=%s where id=%s", (c_aml.date, aml.id))
                            #     self.env.cr.commit()
                                # aml.write({'date': c_aml.date})     
                        continue            
                if not invoice_line:
                    a = open('journal_balance.csv', 'a+')
                    a.write("%s,%s,'no invoice to correct the amount'\n" % (aml.name, aml.move_id.name))
                    a.close()                            

    def correct_date(self, offset=0, limit=10000):        
        for move in self.env['account.move'].search([('journal_id', '=', 6), ('date', '<', '2021-07-01')], offset=offset, limit=limit):
            order = move.stock_move_id.picking_id.sale_id
            invoice_line = self.env['account.invoice.line'].search([('stock_move_ids', 'in', move.stock_move_id.ids)])
            invoice = invoice_line.mapped('invoice_id')
            if not invoice:
                pick = self.env['stock.picking'].search([('name', '=', move.ref)])
                invoice = pick.sale_id.invoice_ids.filtered(lambda rec: rec.state not in ('cancel', 'draft'))
                # .mapped('invoice_line_ids').filtered(lambda r: r.product_id.id == aml.product_id.id)
            if len(invoice) != 1:
                a = open('date_correct.csv', 'a+')
                a.write("%s,%s, 'multiple invoice'\n" % (move.name, order.name or ''))
                a.close()
                continue
            aml = invoice.move_id
            if not aml:
                a = open('issues.csv', 'a+')
                a.write("%s,%s,'aml not found in invoice'\n" % (move.name, order.name or ''))
                a.close()
                continue
            if aml.date != move.date:
                # print("update account_move set date=%s where id=%s" %(aml.date, move.id))
                self.env.cr.execute("update account_move set date=%s where id=%s", (aml.date, move.id))
                self.env.cr.execute("update account_move_line set date=%s where move_id=%s", (aml.date, move.id))
                self.env.cr.commit()

