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

    @api.depends('invoice_ids')
    def _get_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.mapped('invoice_ids'))

    @api.onchange('bank_stmt_line_id')
    def onchange_bank_stmt(self):
        if self.bank_stmt_line_id:
            cheque_no = self.bank_stmt_line_id.name and self.bank_stmt_line_id.name.split('CK#:')
            if cheque_no and len(cheque_no) > 1:
                cheque_no = cheque_no[1].split(' ', 1)[0]
                cheque_no_strip = cheque_no.lstrip('0')
                payments = self.env['account.payment'].search(['|', ('communication', '=', cheque_no_strip), ('communication', '=', cheque_no)])
                self.payment_ids = payments.ids
                self.partner_ids = payments.mapped('partner_id').ids
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
