# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ProcessReturnedCheck(models.Model):
    _inherit = ['mail.thread']
    _name = 'process.returned.check'
    _description = 'Procedd Returned Check'

    bank_stmt_line_id = fields.Many2one('account.bank.statement.line',
        string='Bank statement line',
        domain=[('name', 'like', 'DEPOSITED ITEM RETURNED'), ('move_name', '!=', False)])
    payment_id = fields.Many2one('account.payment', string='Payment',
        domain=[('payment_type', '=', 'inbound'),
        ('payment_method_id.code', 'in', ('check_printing_in', 'batch_payment')),
        ('is_return_cleared', '=', False), ('state', 'not in', ('draft', 'cancelled'))])
    check_no = fields.Char(related='payment_id.communication', string='Chaek Number')
    partner_id = fields.Many2one('res.partner', related='payment_id.partner_id', string='Partner')
    state = state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')], default='draft',
        copy=False, track_visibility='onchange', required=True)

    @api.onchange('bank_stmt_line_id')
    def onchange_discount(self):
        if self.bank_stmt_line_id:
            cheque_no = self.bank_stmt_line_id.name and self.bank_stmt_line_id.name.split('CK#:')
            if cheque_no and len(cheque_no) > 1:
                cheque_no = cheque_no[1].split(' ', 1)[0]
                cheque_no_strip = cheque_no.lstrip('0')
                payment = self.env['account.payment'].search(['|', ('communication', '=', cheque_no_strip), ('communication', '=', cheque_no)], limit=1)
                self.payment_id = payment.id
        else:
            self.payment_id = False

    @api.multi
    def process_payment(self):
        for rec in self:
            payment = rec.payment_id
            invoice = payment.invoice_ids
            payment.move_line_ids.remove_move_reconcile()
            reconcile_lines = (payment.move_line_ids | self.bank_stmt_line_id.journal_entry_ids)
            reconcile_lines = reconcile_lines.filtered(lambda r: not r.reconciled and r.account_id.internal_type in ('payable', 'receivable'))
            reconcile_lines.reconcile()
            invoice.remove_sale_commission(self.bank_stmt_line_id.date)
            rec.state = 'done'
            payment.is_return_cleared = True

    @api.multi
    def action_cancel(self):
        for rec in self:
            rec.state = 'cancel'



ProcessReturnedCheck()
