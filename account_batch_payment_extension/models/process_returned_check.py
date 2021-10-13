# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ProcessReturnedCheck(models.Model):
    _inherit = ['mail.thread']
    _name = 'process.returned.check'
    _description = 'Process Returned Check'

    bank_stmt_line_id = fields.Many2one('account.bank.statement.line',
        string='Bank statement line')
    payment_ids = fields.Many2many('account.payment', string='Payment')
    partner_ids = fields.Many2many('res.partner', string='Partner')
    invoice_ids = fields.Many2many('account.invoice', string='Invoice')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')], default='draft',
        copy=False, track_visibility='onchange', required=True)
    invoice_count = fields.Integer(string='Invoice Count', compute='_get_invoice_count', readonly=True)
    notes = fields.Text(string='Notes')
    amount = fields.Monetary(related='bank_stmt_line_id.amount', string='Amount', digits=0, currency_field='journal_currency_id')
    journal_currency_id = fields.Many2one('res.currency', string="Journal's Currency", related='bank_stmt_line_id.journal_currency_id',
        help='Utility field to express amount currency', readonly=True)

    @api.depends('invoice_ids')
    def _get_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.mapped('invoice_ids'))

    @api.onchange('partner_ids')
    def onchange_partner(self):
        if self.partner_ids:
            self.payment_ids = self.payment_ids.filtered(lambda r: r.partner_id in self.partner_ids)
        else:
            self.payment_ids = False

    @api.onchange('bank_stmt_line_id')
    def onchange_bank_stmt(self):
        self.payment_ids = False
        self.partner_ids = False
        if self.bank_stmt_line_id:
            cheque_no = self.bank_stmt_line_id.name and self.bank_stmt_line_id.name.split('CK#:')
            if cheque_no and len(cheque_no) > 1:
                cheque_no = cheque_no[1].split(' ', 1)[0]
                cheque_no_strip = cheque_no.lstrip('0')
                payments = self.env['account.payment'].search(['|',
                    ('communication', '=', cheque_no_strip),
                    ('communication', '=', cheque_no),
                    ('amount', '=', abs(self.amount))])
                if payments and len(payments) == 1:
                    self.partner_ids = payments.mapped('partner_id').ids
                    self.payment_ids = payments.ids
        else:
            self.payment_ids = False
            self.partner_ids = False

    @api.multi
    def process_payment(self):
        for rec in self:
            payment = rec.payment_ids
            invoice = payment.mapped('invoice_ids')
            if not payment:
                raise UserError("Payment is not selected")
            for pay in payment:
                pay.write({'old_invoice_ids': [(6, 0, pay.reconciled_invoice_ids.ids)]})
                pay.mapped('move_line_ids').remove_move_reconcile()
            reconcile_lines = (payment.mapped('move_line_ids') | self.bank_stmt_line_id.journal_entry_ids)
            reconcile_lines = reconcile_lines.filtered(lambda r: not r.reconciled and r.account_id.internal_type in ('payable', 'receivable'))
            reconcile_lines.reconcile()
            if invoice:
                fine_invoices = invoice.remove_sale_commission(self.bank_stmt_line_id.date)
                if fine_invoices:
                    self.invoice_ids = fine_invoices
            rec.state = 'done'
            payment.write({'is_return_cleared': True})
            rec.bank_stmt_line_id.is_return_cleared = True

    def undo_process(self):
        for payment in self.payment_ids:
            if payment.old_invoice_ids:
                old_invoice_not_open = payment.old_invoice_ids.filtered(lambda r: r.state != 'open')
                if old_invoice_not_open:
                    raise UserError("Invoice not in open state \n %s" %
                                    ', '.join(old_invoice_not_open.mapped('number')))
                payment.mapped('move_line_ids').remove_move_reconcile()
                credit_aml = payment.mapped('move_line_ids').filtered(lambda r: not r.reconciled and r.account_id.internal_type in ('payable', 'receivable'))
                payment.old_invoice_ids.register_payment(credit_aml)
                payment.old_invoice_ids.remove_bounced_cheque_commission()
        if self.invoice_ids:
            paid_fine = self.invoice_ids.filtered(lambda r: r.state == 'paid')
            if paid_fine:
                raise UserError("Check Bounce Return Invoice already Paid. \n %s" %
                                ', '.join(paid_fine.mapped('number')))
            self.invoice_ids.action_invoice_cancel()
        self.state = 'cancel'
        payment.write({'is_return_cleared': False})
        self.bank_stmt_line_id.is_return_cleared = False



    @api.multi
    def action_cancel(self):
        for rec in self:
            rec.state = 'cancel'

    @api.multi
    def name_get(self):
        result = []
        for record in self:
            name = 'Returned Check ' + str(record.id)
            result.append((record.id, name))
        return result

    @api.multi
    def action_view_invoice(self):
        invoices = self.mapped('invoice_ids')
        action = self.env.ref('account.action_invoice_tree1').read()[0]
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref('account.invoice_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state,view) for state,view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = invoices.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action


ProcessReturnedCheck()
