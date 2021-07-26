# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.tools import float_round
from odoo.exceptions import UserError

class BatchPaymentCommon(models.Model):

    _inherit = ['mail.thread']
    _name = 'batch.payment.common'

    name = fields.Char(string='Batch Picking Name', default='New',
        copy=False, required=True, help='Name of the batch payment')
    cash_collected_lines = fields.One2many('cash.collected.lines', 'common_batch_id',
        string='Cash Collected Breakup')
    payment_ids = fields.One2many('account.payment', 'common_batch_id', string='Payments')
    actual_returned = fields.Float(string='Total Amount',
        help='Total amount returned by the driver.',
        digits=dp.get_precision('Product Price'))
    is_posted = fields.Boolean(string="Posted")
    pending_amount = fields.Float(string="Difference",
        compute='_calculate_pending_amount')
    batch_payment_count = fields.Integer(string='Batch Payment',
        compute='_compute_batch_payment_count')
    cash_amount = fields.Float(string='Cash Amount',
        digits=dp.get_precision('Product Price'))
    cheque_amount = fields.Float(string='Check Amount',
        digits=dp.get_precision('Product Price'))
    show_warning = fields.Boolean(string='Pending Line Warning')
    state = state = fields.Selection([
        ('draft', 'Draft'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled')], default='draft',
        copy=False, track_visibility='onchange', required=True)


    @api.multi
    @api.depends('payment_ids')
    def _compute_batch_payment_count(self):
        for rec in self:
            rec.batch_payment_count = len(rec.payment_ids.mapped('batch_payment_id'))

    @api.model
    def create(self, vals):
        if vals.get('name', 'new') == 'new':
            vals['name'] = self.env['ir.sequence'].next_by_code('batch.payment.common') or 'new'
        return super(BatchPaymentCommon, self).create(vals)

    @api.multi
    @api.depends('actual_returned', 'cash_collected_lines', 'cash_collected_lines.amount')
    def _calculate_pending_amount(self):
        for batch in self:
            real_collected = 0
            for cash_line in batch.cash_collected_lines:
                real_collected += float_round(cash_line.amount, precision_digits=2)
            batch.pending_amount = float_round(batch.actual_returned - real_collected, precision_digits=2)

    @api.multi
    def view_payments(self):
        payments = self.payment_ids
        action = self.env.ref('account.action_account_payments').read()[0]
        if len(payments) > 1:
            action['domain'] = [('id', 'in', payments.ids)]
        elif len(payments) == 1:
            action['views'] = [(self.env.ref('account.view_account_payment_form').id, 'form')]
            action['res_id'] = payments.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    @api.multi
    def view_batch_payments(self):
        self.ensure_one()
        payments = self.payment_ids
        batch_payments = payments.mapped('batch_payment_id')
        action = self.env.ref('account_batch_payment.action_batch_payment_in').read()[0]

        if len(batch_payments) > 1:
            action['domain'] = [('id', 'in', batch_payments.ids)]
        elif len(batch_payments) == 1:
            action['views'] = [(self.env.ref('account_batch_payment.view_batch_payment_form').id, 'form')]
            action['res_id'] = batch_payments.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}

        return action

    @api.multi
    def register_payments(self):
        for batch in self:
            if batch.pending_amount:
                raise UserError(_('Total Amount mismatch'))
            if float_round(batch.cheque_amount + batch.cash_amount, precision_digits=2) != float_round(batch.actual_returned, precision_digits=2):
                raise UserError(_('Total amount and sum of Cash and Check does not match'))
            if not batch.actual_returned:
                raise UserError(_('Please properly enter the returned amount'))
            if not batch.cash_collected_lines:
                raise UserError(_('Please add cash collected lines before proceeding.'))
            if batch.cash_collected_lines and all(l.amount > 0 for l in batch.cash_collected_lines):
                batch.cash_collected_lines.create_from_common_batch_payment()
            else:
                batch.show_warning = True
                return
            batch.show_warning = False
            batch.is_posted = True
            batch.state = 'paid'
