# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class Accountinvoice(models.Model):
    _inherit = "account.invoice"

    def remove_bounced_cheque_commission(self):
        for invoice in self:
            commission_rec = self.env['sale.commission'].search([
                ('invoice_id', '=', invoice.id), ('is_paid', '=', True),
                ('is_cancelled', '=', False), ('invoice_type', '=', 'bounced_cheque')])
            for rec in commission_rec:
                if rec.is_settled:
                    rec.is_cancelled = True
                    sale = invoice.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')
                    commission = rec.commission
                    vals1 = {
                        'sale_person_id': rec.sale_person_id.id,
                        'sale_id': sale and sale.id,
                        'commission': -commission,
                        'invoice_id': invoice.id,
                        'invoice_type': 'bounced_reverse',
                        'is_paid': True,
                        'invoice_amount': invoice.amount_total,
                        'commission_date': date.today(),
                        'paid_date': date.today(),
                    }
                    refund_rec = self.env['sale.commission'].create(vals1)
                else:
                    rec.unlink()
        return {}

    def remove_sale_commission(self, invoice_date):

        invoice_fine = self.env['account.invoice']

        for invoice in self:
            commission_rec = self.env['sale.commission'].search([
                ('invoice_id', '=', invoice.id), ('is_paid', '=', True),
                ('is_cancelled', '=', False), ('invoice_type', '=', 'out_invoice')])
            for rec in commission_rec:
                if rec.is_settled:
                    rec.is_cancelled = True
                    sale = invoice.invoice_line_ids.mapped('sale_line_ids')
                    commission = rec.commission
                    vals1 = {
                        'sale_person_id': rec.sale_person_id.id,
                        'sale_id': sale and sale[-1].order_id.id,
                        'commission': -commission,
                        'invoice_id': invoice.id,
                        'invoice_type': 'bounced_cheque',
                        'is_paid': True,
                        'invoice_amount': invoice.amount_total,
                        'commission_date': date.today(),
                        'paid_date': date.today(),
                    }
                    refund_rec = self.env['sale.commission'].create(vals1)
                    vals2 = {
                        'sale_person_id': rec.sale_person_id.id,
                        'sale_id': sale and sale[-1].order_id.id,
                        'commission': commission,
                        'invoice_id': invoice.id,
                        'invoice_type': 'out_invoice',
                        'is_paid': False,
                        'invoice_amount': invoice.amount_total,
                        'commission_date': invoice.date_invoice and invoice.date_invoice
                    }
                    new_rec = self.env['sale.commission'].create(vals2)
                else:
                    rec.is_paid = False
        check_bounce_product = invoice.company_id.check_bounce_product or False
        if not check_bounce_product:
            raise UserError(_('Check Bounce Product is not configured in Company'))
        check_bounce_term = invoice.company_id.check_bounce_term or False
        if not check_bounce_term:
            raise UserError(_('Check Bounce Payment Term is not configured in Company'))
        partner_list = []
        bounce_invoice = []
        for invoice in self:
            if invoice.partner_id.id in partner_list:
                continue
            fpos = invoice.fiscal_position_id
            account = check_bounce_product.product_tmpl_id.get_product_accounts(fpos)
            if account and account.get('income', ''):
                account = account['income']
            line_vals = [(0, 0, {
                'name': 'Returned check service fee',
                'account_id': account.id,
                'product_id': check_bounce_product.id,
                'price_unit': check_bounce_product.cost,
                'quantity': 1.0,
                'discount': 0.0,
            })]
            invoice_vals = {
                'type': 'out_invoice',
                'reference': False,
                'date_invoice': invoice_date or date.today(),
                'account_id': invoice.account_id.id,
                'partner_id': invoice.partner_id.id,
                'partner_shipping_id': invoice.partner_shipping_id.id,
                'invoice_line_ids': line_vals,
                'currency_id': invoice.currency_id.id,
                'payment_term_id': check_bounce_term.id,
                'fiscal_position_id': invoice.fiscal_position_id and invoice.fiscal_position_id.id,
                'team_id': invoice.team_id.id,
                'check_bounce_invoice': True
            }
            invoice_fine = self.env['account.invoice'].create(invoice_vals)
            bounce_invoice.append(invoice_fine.id)
            partner_list.append(invoice.partner_id.id)
        return bounce_invoice


Accountinvoice()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    st_date = fields.Date(related='statement_line_id.date', readonly=True, store=True, string='Statement Date')


AccountMoveLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
