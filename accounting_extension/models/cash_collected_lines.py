from odoo import fields, models, api, _
from odoo.exceptions import UserError

from odoo.addons import decimal_precision as dp


class CashCollectedLines(models.Model):
    _inherit = 'cash.collected.lines'

    discount = fields.Float(string='Discount(%)')
    discount_amount = fields.Float(string='Discount', digits=dp.get_precision('Product Price'))

    @api.onchange('invoice_id')
    def onchange_invoice_id(self):
        if self.invoice_id:
            self.amount = self.invoice_id.residual
            days = (self.invoice_id.date_invoice - fields.Date.context_today(self)).days
            if self.invoice_id.payment_term_id.is_discount and abs(days) < self.invoice_id.payment_term_id.due_days:
                self.discount = self.invoice_id.payment_term_id.discount_per
                self.discount_amount = self.invoice_id.residual * (self.discount / 100)
                self.amount = self.invoice_id.residual - self.discount_amount
            else:
                self.discount = 0

    @api.onchange('discount')
    def onchange_discount(self):
        if self.invoice_id:
            self.discount_amount = self.invoice_id.residual * (self.discount / 100)
            self.amount = self.invoice_id.residual - self.discount_amount

    @api.onchange('discount_amount')
    def onchange_discount_amount(self):
        if self.invoice_id:
            self.discount = (self.discount_amount / self.invoice_id.residual) * 100
            self.amount = self.invoice_id.residual - self.discount_amount

    @api.multi
    def create_payment(self):

        batch_payment_info = {}

        for line in self:
            if not line.amount:
                continue

            need_writeoff = True if line.discount else False

            if need_writeoff and not self.env.user.company_id.discount_account_id:
                raise UserError(_('Please set a discount account in company.'))
            if line.invoice_id:
                batch_payment_info.setdefault(line.journal_id, {}). \
                    setdefault(line.payment_method_id, []). \
                    append({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'payment_method_id': line.payment_method_id.id,
                    'partner_id': line.partner_id.id,
                    'amount': line.amount,
                    'journal_id': line.journal_id.id,
                    'invoice_ids': [(6, 0, line.invoice_id.ids)],
                    'communication': line.communication,
                    'batch_id': line.batch_id.id,
                    'discount_amount': line.discount_amount,
                    'payment_difference_handling': 'reconcile' if need_writeoff else False,
                    'writeoff_label': line.invoice_id.payment_term_id.name if need_writeoff else False,
                    'writeoff_account_id': self.env.user.company_id.discount_account_id.id if need_writeoff else False
                })
                if line.invoice_id:
                    line.invoice_id.write({'discount_from_batch': line.discount})
            else:
                batch_payment_info.setdefault(line.journal_id, {}). \
                    setdefault(line.payment_method_id, []). \
                    append({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'payment_method_id': line.payment_method_id.id,
                    'partner_id': line.partner_id.id,
                    'amount': line.amount,
                    'journal_id': line.journal_id.id,
                    'communication': line.communication,
                    'batch_id': line.batch_id.id,
                })

        AccountBatchPayment = self.env['account.batch.payment']

        for journal, batch_vals in batch_payment_info.items():
            for payment_method, payment_vals in batch_vals.items():
                AccountBatchPayment.create({
                    'batch_type': 'inbound',
                    'journal_id': journal.id,
                    'payment_ids': [(0, 0, vals) for vals in payment_vals],
                    'payment_method_id': payment_method.id,
                })
    @api.multi
    def create_from_common_batch_payment(self):

        batch_payment_info = {}

        for line in self:
            if not line.amount:
                continue

            need_writeoff = True if line.discount else False

            if need_writeoff and not self.env.user.company_id.discount_account_id:
                raise UserError(_('Please set a discount account in company.'))
            if line.invoice_id:
                batch_payment_info.setdefault(line.journal_id, {}). \
                    setdefault(line.payment_method_id, []). \
                    append({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'payment_method_id': line.payment_method_id.id,
                    'partner_id': line.partner_id.id,
                    'amount': line.amount,
                    'journal_id': line.journal_id.id,
                    'invoice_ids': [(6, 0, line.invoice_id.ids)],
                    'communication': line.communication,
                    'common_batch_id': line.common_batch_id.id,
                    'discount_amount': line.discount_amount,
                    'payment_difference_handling': 'reconcile' if need_writeoff else False,
                    'writeoff_label': line.invoice_id.payment_term_id.name if need_writeoff else False,
                    'writeoff_account_id': self.env.user.company_id.discount_account_id.id if need_writeoff else False
                })
                if line.invoice_id:
                    line.invoice_id.write({'discount_from_batch': line.discount})
            else:
                batch_payment_info.setdefault(line.journal_id, {}). \
                    setdefault(line.payment_method_id, []). \
                    append({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'payment_method_id': line.payment_method_id.id,
                    'partner_id': line.partner_id.id,
                    'amount': line.amount,
                    'journal_id': line.journal_id.id,
                    'communication': line.communication,
                    'common_batch_id': line.common_batch_id.id,
                })

        AccountBatchPayment = self.env['account.batch.payment']

        for journal, batch_vals in batch_payment_info.items():
            for payment_method, payment_vals in batch_vals.items():
                AccountBatchPayment.create({
                    'batch_type': 'inbound',
                    'journal_id': journal.id,
                    'payment_ids': [(0, 0, vals) for vals in payment_vals],
                    'payment_method_id': payment_method.id,
                })
