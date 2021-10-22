# -*- coding: utf-8 -*-

from odoo import models, fields, api,_
from datetime import datetime
from odoo.exceptions import UserError


class GenerateDiscountCheck(models.TransientModel):

    _name = 'generate.discount.check'
    _description = 'Generate Discount Check'

    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    wizard_invoice_ids = fields.One2many('vendor.bill.lines.wizard', 'generate_check_id', string='Invoices')


    @api.onchange('start_date', 'end_date')
    def get_invoices(self):
        vals={}
        if self.start_date and self.end_date:
            vendor_bills1 = self.env['account.invoice']
            vendor_bills = self.env['account.invoice'].search([('type','=','in_invoice'), ('state', '=', 'open'), ('discount_due_date', '>', self.start_date), ('discount_due_date', '<', self.end_date)])

            vendor_bills1 = self.env['account.invoice'].search([('type','=','in_invoice'), ('state', '=', 'open'), ('date_due', '>', self.start_date), ('date_due', '<', self.end_date), ('discount_due_date', '=', False)])
            vendor_bills |= vendor_bills1
            self.wizard_invoice_ids = False
            lines = []
            for bill in vendor_bills:
                if bill.discount_due_date and bill.discount_due_date >= fields.Date.today():
                    discount_total_amount = bill.residual_signed * (100 - bill.payment_term_id.discount_per) / 100
                else:
                    discount_total_amount = 0.00
                val = {
                    'total_amount': bill.residual_signed,
                    'partner_id': bill.partner_id.id,
                    'discount_amount': discount_total_amount,
                    'invoice_id': bill.id,
                    'date_invoice': bill.date_invoice,
                    'date_due': bill.date_due,
                    'discount_due_date': bill.discount_due_date,
                    'discount_amount_pseudo': discount_total_amount,
                    'invoice_id_pseudo': bill.id,
                    'select': True,
                }
                lines.append(val)

            vals.update({'wizard_invoice_ids': lines})
            return {'value' : vals}


    @api.multi
    def generate_check(self):

        bank_journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        payment_method = self.env['account.payment.method'].search([('code', '=', 'check_printing'), ('payment_type', '=', 'outbound')], limit=1)
        company_id = self.env['res.users'].browse(self.env.uid).company_id
        purchase_writeoff_account = self.env['res.users'].browse(self.env.uid).company_id.purchase_writeoff_account_id
        if not bank_journal:
            raise UserError(_('Bank journal not defined! \nPlease create a bank journal in the system to process these transactions.'))
        if not purchase_writeoff_account:
                raise UserError(_('Please add a purchase writeoff account in the company form page.'))
        partner_group = {}
        for invoice in self.wizard_invoice_ids:
            discount_flag = False
            if not invoice.select:
                continue
            bill = invoice.invoice_id
            if bill.discount_due_date and bill.discount_due_date >= fields.Date.today():
                discount_flag = True
                payment_line = {
                    'invoice_id': bill.id,
                    'discount': invoice.total_amount - invoice.discount_amount,
                    'discounted_total': invoice.discount_amount,
                    'amount_total': invoice.total_amount,
                    'currency_id': bill.currency_id and bill.currency_id.id,
                    'discount_percentage': bill.payment_term_id.discount_per,
                    'reference': bill.reference,
                    'invoice_date': invoice.date_invoice,
                    'payment_amount': invoice.discount_amount,
                    'is_full_reconcile': True
                    }
            if bill.partner_id.id in partner_group:
                partner_group[bill.partner_id.id][0] += invoice.discount_amount if discount_flag else invoice.total_amount
                partner_group[bill.partner_id.id][1].append((4, bill.id, 0))
                if discount_flag:
                    partner_group[bill.partner_id.id][2].append((0, 0, payment_line))
            else:
                partner_group[bill.partner_id.id] = [invoice.discount_amount, [(4, bill.id, 0)], [(0, 0, payment_line)]] if discount_flag else [invoice.total_amount, [(4, bill.id, 0)], []]

        payments = self.env['account.payment']
      
        for partner in partner_group:
            payment_vals = {
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'payment_method_id': payment_method.id,
                'partner_id': partner,
                'amount': partner_group[partner][0],
                'journal_id': bank_journal.id,
                'invoice_ids': partner_group[partner][1]
            }
            if partner_group[partner][2]:
                payment_vals.update({
                    'payment_difference_handling': 'reconcile',
                    'writeoff_label': 'Discount',
                    'writeoff_account_id': purchase_writeoff_account.id,
                    'payment_lines': partner_group[partner][2]
                })
            payments |= payments.create(payment_vals)
        action = self.env.ref('account.action_account_payments_payable').read()[0]
        action['domain'] = [('id', 'in', payments.ids)]
        return action



GenerateDiscountCheck()

class VendorBillLines(models.TransientModel):

    _name = 'vendor.bill.lines.wizard'
    _description = 'Vendor Bill Lines Wizard'

    total_amount = fields.Float(string='Total Amount')
    partner_id = fields.Many2one('res.partner', string='Vendor')
    discount_amount = fields.Float('Discount')
    discount_amount_pseudo = fields.Float('Amount After Discount')
    invoice_id = fields.Many2one('account.invoice', string='Invoice Source')
    invoice_id_pseudo = fields.Many2one('account.invoice', string='Invoice')
    generate_check_id = fields.Many2one('generate.discount.check', string='Parent')
    date_invoice = fields.Date(string='Bill Date')
    date_due = fields.Date(string='Due Date')
    discount_due_date = fields.Date(string='Discount Due Date')
    select = fields.Boolean(string='Select')

VendorBillLines()
