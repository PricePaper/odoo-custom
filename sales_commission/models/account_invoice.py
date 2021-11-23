# -*- coding: utf-8 -*-

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields, models, api, _
from odoo.exceptions import UserError


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    sales_person_ids = fields.Many2many('res.partner', string='Associated Sales Persons')
    check_bounce_invoice = fields.Boolean(string='Check Bounce Invoice', default=False)
    sale_commission_ids = fields.One2many('sale.commission', 'invoice_id', string='Commission')
    paid_date = fields.Date(string='Paid_date', compute='_compute_paid_date')
    commission_rule_ids = fields.Many2many('commission.rules', string='Commission Rules')

    @api.model
    def _prepare_refund(self, invoice, date_invoice=None, date=None, description=None, journal_id=None):
        values = super(AccountInvoice, self)._prepare_refund(invoice, date_invoice, date, description, journal_id)
        if invoice.sales_person_ids:
            values['sales_person_ids'] = [(6, 0, invoice.sales_person_ids.ids)]
        if invoice.commission_rule_ids:
            values['commission_rule_ids'] = [(6, 0, invoice.commission_rule_ids.ids)]
        return values

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner_id(self):
        res = super(AccountInvoice, self)._onchange_partner_id()
        if self.partner_id and self.partner_id.sales_person_ids:
            self.sales_person_ids = self.partner_id.sales_person_ids
        return res

    @api.multi
    @api.onchange('sales_person_ids')
    def onchange_sales_person_ids(self):
        if self.sales_person_ids:
            rules = self.partner_id.mapped('commission_percentage_ids').filtered(lambda r:r.sale_person_id in self.sales_person_ids).mapped('rule_id')
            if rules:
                sale_rep = rules.mapped('sales_person_id')
                non_sale_rep = self.sales_person_ids - sale_rep
                for rep in non_sale_rep:
                    rules |= rep.default_commission_rule
            else:
                for rep in self.sales_person_ids:
                    rules |= rep.mapped('default_commission_rule')
            self.commission_rule_ids = rules
        else:
            self.commission_rule_ids = False

    def _compute_paid_date(self):
        for rec in self:
            if rec.state == 'paid':
                paid_date_list = rec.payment_move_line_ids.mapped('date')
                if paid_date_list:
                    rec.paid_date = max(paid_date_list)

    @api.multi
    def action_invoice_re_open(self):
        for invoice in self:
            commission_rec = self.env['sale.commission'].search([('invoice_id', '=', invoice.id)])
            settled_rec = commission_rec.filtered(
                lambda r: r.is_settled and r.invoice_type != 'unreconcile' and not r.is_cancelled)
            for rec in settled_rec:
                commission = rec.commission
                vals = {
                    'sale_person_id': rec.sale_person_id.id,
                    'commission': -commission,
                    'invoice_id': invoice.id,
                    'invoice_type': 'unreconcile',
                    'is_paid': True,
                    'invoice_amount': self.amount_total,
                    'commission_date': date.today(),
                    'paid_date': date.today(),
                }
                self.env['sale.commission'].create(vals)
                rec.is_cancelled = True

            paid_rec = commission_rec.filtered(lambda r: not r.is_settled and r.invoice_type != 'unreconcile')
            paid_rec and paid_rec.unlink()
        res = super(AccountInvoice, self).action_invoice_re_open()
        return res

    @api.multi
    def invoice_validate(self):
        res = super(AccountInvoice, self).invoice_validate()
        for invoice in self:
            if invoice.check_bounce_invoice or invoice.residual == 0:
                continue
            rec = invoice.sudo().calculate_commission()
        return res

    @api.multi
    def action_invoice_paid(self):
        res = super(AccountInvoice, self).action_invoice_paid()
        for invoice in self:
            if invoice.check_bounce_invoice:
                continue
            rec = invoice.sudo().calculate_commission()
            if rec and invoice.state == 'paid':
                rec.sudo().write({'is_paid': True})
                if invoice.payment_ids:
                    invoice.sudo().check_commission(rec)
                    if invoice.type != 'out_refund':
                        invoice.sudo().check_due_date(rec)
        return res

    def check_commission(self, lines):
        for line in lines:
            profit = self.gross_profit
            commission = line.commission
            payment_date = self.paid_date

            rule_id = self.commission_rule_ids.filtered(
                lambda r: r.sales_person_id == line.sale_person_id)
            if rule_id:
                if rule_id.based_on in ['profit', 'profit_delivery']:
                    if profit <= 0:
                        line.write({'commission': 0})
                        continue
                    commission = profit * (rule_id.percentage / 100)
                elif rule_id.based_on == 'invoice':
                    amount = self.amount_total
                    commission = amount * (rule_id.percentage / 100)
            line.write({'commission': commission})
            if self._context.get('is_cancelled') and commission < 0:
                line.is_cancelled = True


    @api.multi
    def action_cancel(self):
        for invoice in self:
            commission_rec = self.env['sale.commission'].search([('invoice_id', '=', invoice.id)])
            settled_rec = commission_rec.filtered(
                lambda r: r.is_settled and not r.is_cancelled and r.invoice_type != 'cancel')
            for rec in settled_rec:
                commission = rec.commission
                vals = {
                    'sale_person_id': rec.sale_person_id.id,
                    'commission': -commission,
                    'invoice_id': invoice.id,
                    'invoice_type': 'cancel',
                    'is_paid': True,
                    'invoice_amount': self.amount_total,
                    'commission_date': date.today(),
                    'paid_date': date.today(),
                }
                self.env['sale.commission'].create(vals)
                rec.is_cancelled = True

            paid_rec = commission_rec.filtered(lambda r: not r.is_settled and r.invoice_type != 'cancel')
            paid_rec and paid_rec.unlink()
        res = super(AccountInvoice, self).action_cancel()
        return res

    def check_due_date(self, lines):
        """
        Apply commission Ageing by checking due date
        """

        for line in lines:
            payment_date = self.paid_date
            if payment_date and payment_date > self.date_due:
                extra_days = payment_date - self.date_due
                if self.partner_id.company_id.commission_ageing_ids:
                    commission_ageing = self.partner_id.company_id.commission_ageing_ids.filtered(
                        lambda r: r.delay_days <= extra_days.days)
                    commission_ageing = commission_ageing.sorted(key=lambda r: r.delay_days, reverse=True)
                    if commission_ageing and commission_ageing[0].reduce_percentage:
                        commission = commission_ageing[0].reduce_percentage * line.commission / 100
                        vals = {
                            'sale_person_id': line.sale_person_id.id,
                            'sale_id': line.sale_id and line.sale_id.id,
                            'commission': -commission,
                            'invoice_id': self.id,
                            'invoice_type': 'aging',
                            'is_paid': True,
                            'invoice_amount': self.amount_total,
                            'commission_date': self.date_invoice and self.date_invoice
                        }
                        commission_rec = self.env['sale.commission'].create(vals)

    def calculate_commission(self):

        if len(self.invoice_line_ids) == 1 and self.invoice_line_ids[0].quantity < 0:
            return False
        commission_rec = self.env['sale.commission'].search([('invoice_id', '=', self.id), ('is_paid', '=', False)])
        if not commission_rec and self.type in ['out_invoice', 'out_refund']:
            profit = self.gross_profit
            # commission_rule = self.partner_id.commission_percentage_ids.filtered(lambda r:r.sale_person_id and r.sale_person_id in self.sales_person_ids)
            commission_rule = self.commission_rule_ids
            for rec in commission_rule:
                commission = 0
                if rec.based_on in ['profit', 'profit_delivery']:
                    commission = profit * (rec.percentage / 100)
                    if profit <= 0:
                        commission =0
                elif rec.based_on == 'invoice':
                    amount = self.amount_total
                    commission = amount * (rec.percentage / 100)
                if commission == 0:
                    continue
                if self.type == 'out_refund':
                    commission = -commission
                sale = self.invoice_line_ids.mapped('sale_line_ids')
                vals = {
                    'sale_person_id': rec.sales_person_id.id,
                    'sale_id': sale and sale[-1].order_id.id,
                    'commission': commission,
                    'invoice_id': self.id,
                    'invoice_type': self.type,
                    'is_paid': False,
                    'invoice_amount': self.amount_total,
                    'commission_date': self.date_invoice and self.date_invoice
                }
                commission_rec = self.env['sale.commission'].create(vals)
        return commission_rec


AccountInvoice()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
