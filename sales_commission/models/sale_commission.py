# -*- coding: utf-8 -*-

from datetime import date
import logging
from odoo import fields, models, api
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from odoo.addons import decimal_precision as dp
from odoo.tools import float_round


class SaleCommission(models.Model):
    _name = 'sale.commission'
    _description = 'Sale Commission'

    sale_person_id = fields.Many2one('res.partner', string='Sale Person')
    commission = fields.Float(string='Commission', digits=dp.get_precision('Product Price'))
    invoice_id = fields.Many2one('account.invoice', string='Invoice')
    is_paid = fields.Boolean(string='Paid', default=False)
    is_cancelled = fields.Boolean(string='Cancelled', default=False)
    invoice_type = fields.Selection(
        selection=[('out_invoice', 'Invoice'), ('out_refund', 'Refund'), ('draw', 'Weekly Draw'),
                   ('bounced_cheque', 'Cheque Bounce'), ('cancel', 'Invoice Cancelled'),
                   ('aging', 'Commission Aging'), ('unreconcile', 'Invoice Unreconciled')], string='Type')
    invoice_amount = fields.Float(string='Amount')
    date_invoice = fields.Date(related='invoice_id.date_invoice', string="Invoice Date", readonly=True, store=True)
    sale_id = fields.Many2one('sale.order', string="Sale Order")
    is_settled = fields.Boolean(string='Settled')
    is_removed = fields.Boolean(string='Removed')
    settlement_id = fields.Many2one('sale.commission.settlement', string='Settlement')
    commission_date = fields.Date('Date')
    paid_date = fields.Date('Paid Date', compute='get_invoice_paid_date', store=True)
    partner_id = fields.Many2one(related='invoice_id.partner_id', string="Customer")

    def link_sc(self, sc_line_id=False, po_line_id=False):
        sc_line = self.env['sale.order.line'].browse(sc_line_id)
        po_line = self.env['purchase.order.line'].browse(po_line_id)
        po_line.write({'sale_line_id': sc_line.id})
        po_line.move_ids.write({'sale_line_id': sc_line.id, 'is_storage_contract': True})
        po_line.invoice_lines.write({'is_storage_contract': True})
        sc_line.order_id.write({'state': 'released', 'sc_po_done': True})

    def find_invoices(self, offset=0, limit=100):
        print(limit)
        no_delivery = []
        unpaid = []
        # print()
        for order in self.env['sale.order'].search([('carrier_id', 'in', [40,42,]), ('create_date', '<', '2021-05-02'), ('invoice_status', '=', 'invoiced')], offset=offset, limit=limit):
            # print(order)
            if not order.order_line.filtered(lambda rec: rec.is_delivery is True):
                if 'paid' in order.invoice_ids.mapped('state') and order.invoice_ids.mapped('sale_commission_ids'):
                    no_delivery.append(order.id)
                # else:
                #     unpaid.append(order.id)
        logging.error('================================>')
        logging.error(no_delivery)
        # logging.error('*********************************>')
        # logging.error(unpaid)

    def correct_commission_aging(self, partner_id=None):
        for invoice in self.env['account.invoice'].search([('state', '=', 'paid'), ('sale_commission_ids', '!=', None), ('type', '=', 'out_invoice')]):
            # print(invoice, invoice.sale_commission_ids)
            if len(invoice.sale_commission_ids) > 1:
                data = {}
                for rec in invoice.sale_commission_ids:
                    if (rec.sale_person_id, rec.commission) in data.keys():
                        data[(rec.sale_person_id, rec.commission)] |=rec
                    else:
                        data[(rec.sale_person_id, rec.commission)] = rec
                for r in data:
                    if len(data[r])>1:
                        unlink_ids = data[r] - data[r][0]

                        logging.error((data[r], unlink_ids))

                        unlink_ids.unlink()
                        data[r] -= unlink_ids
                        try:
                            invoice.check_due_date(data[r])
                        except Exception as e:
                            logging.error(('@@@@@@@@@@@@@@@@@@', e, invoice))
                        logging.error(('*******', invoice))

    def correct_weekly_draw(self):
        res = []
        for rec in self.search([('invoice_type', '=', 'draw')], order='sale_person_id'):
            if not rec.commission_date:
                res.append({'invoice_id':rec.invoice_id.id, 'number': rec.invoice_id.number, 'exception': 'no date', 'commission': rec.id,})
                continue
            if rec.commission_date.weekday() < 5:
                weekly_draw = rec.sale_person_id.weekly_draw
                if weekly_draw and weekly_draw > 0:
                    daily_amount = weekly_draw / 5
                res.append({'commission': rec.id, 'number': rec.invoice_id.number, 'exception': 'week day', 'commission_s': rec.commission, 'commission_o': -daily_amount})
                rec.commission = -daily_amount
            else:
                res.append({'invoice_id':rec.invoice_id.id, 'number': rec.invoice_id.number, 'exception': 'weekend day', 'commission_s': rec.commission,})
                rec.unlink()
        return res

    def compare_commission(self, invoice_ids=[], is_update=False):
        print(self, invoice_ids)
        res = []
        if not invoice_ids:
            return []
        date = datetime. strptime('2021-05-02 00:00:00', '%Y-%m-%d %H:%M:%S')
        for invoice in self.env['account.invoice'].browse(invoice_ids):
            rules = invoice.partner_id.commission_percentage_ids
            if not rules or not invoice.sale_commission_ids:
                 # res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'no commission'})
                 continue
            order = invoice.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')
            profit = invoice.gross_profit
            print(order, order.create_date)
            if order and order.create_date < date and order.carrier_id.id in [40,42,] and order.gross_profit != invoice.gross_profit:
                if not order.order_line.filtered(lambda rec: rec.is_delivery is True):
                    order.adjust_delivery_line()
                profit = order.gross_profit
            aging = {}
            amount = invoice.amount_total
            payment_date_list = [r.payment_date for r in invoice.payment_ids]
            payment_date = max(payment_date_list) if payment_date_list else False
            if invoice.payment_term_id.due_days:
                days = invoice.payment_term_id.due_days
                if payment_date and payment_date > invoice.date_invoice + relativedelta(days=days):
                    profit += invoice.amount_total * (invoice.payment_term_id.discount_per / 100)
                elif payment_date and  payment_date < invoice.date_invoice + relativedelta(days=days):
                    amount -= invoice.amount_total * (invoice.payment_term_id.discount_per / 100)
            if invoice.payment_ids and invoice.payment_ids[0].payment_method_id.code == 'credit_card' and invoice.partner_id.payment_method != 'credit_card':
                profit -= invoice.amount_total * 0.03
            if invoice.payment_ids and invoice.payment_ids[0].payment_method_id.code == 'credit_card':
                amount -= invoice.amount_total * 0.03
            if invoice.payment_ids and invoice.payment_ids[0].payment_method_id.code != 'credit_card' and invoice.partner_id.payment_method == 'credit_card':
                profit += invoice.amount_total * 0.03
            for user in invoice.sales_person_ids:
                if user.id not in invoice.sale_commission_ids.mapped('sale_person_id').ids:
                    rule = rules.filtered(lambda r: r.sale_person_id.id == user.id)
                    commission = 0
                    if rule.rule_id.based_on in ['profit', 'profit_delivery']:
                        commission = profit * (rule.rule_id.percentage / 100)
                    elif rule.rule_id.based_on == 'invoice':
                        # amount = invoice.amount_total
                        commission = amount * (rule.rule_id.percentage / 100)
                    if invoice.type == 'out_refund':
                        commission = -commission
                    vals = {
                        'sale_person_id': user.id,
                        'sale_id': order and order.id,
                        'commission': commission,
                        'invoice_id': invoice.id,
                        'invoice_type': invoice.type,
                        'is_paid': True,
                        'invoice_amount': invoice.amount_total,
                        'commission_date': invoice.date_invoice and invoice.date_invoice
                    }
                    if is_update:
                        commission_rec = self.env['sale.commission'].create(vals)
                        res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'commission not added', 'commission':commission_rec.id})
                    else:
                        res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'commission not added',})
            continue
            # for rec in invoice.sale_commission_ids:
            #     if rec.invoice_type not in ('out_invoice', 'out_refund'):
            #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': rec.invoice_type, 'commission':rec.id})
            #         continue
            #     rule = rules.filtered(lambda r: r.sale_person_id.id == rec.sale_person_id.id)
            #     if not rule and is_update:
            #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'no rule', 'commission':rec.id})
            #         rec.write({'is_removed': True})
            #         continue
            #     if rec.sale_person_id.id not in invoice.partner_id.sales_person_ids.ids and is_update:
            #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'sales person not configured', 'commission':rec.id})
            #         rec.write({'is_removed': True})
            #         continue
            #     commission = 0
            #     if rule.rule_id.based_on in ['profit', 'profit_delivery']:
            #         commission = profit * (rule.rule_id.percentage / 100)
            #     elif rule.rule_id.based_on == 'invoice':
            #         # amount = invoice.amount_total
            #         commission = amount * (rule.rule_id.percentage / 100)
            #     if invoice.type == 'out_refund':
            #         commission = -commission
            #     print(commission, rec.commission)
            #     if round(rec.commission, 2) != round(commission, 2):
            #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'commission difference', 'commission':rec.id,
            #             'commission_s':rec.commission, 'commission_o': commission, 'profit':profit, 'amount': amount})
            #         rec.write({'commission': commission})
            #         continue
                # if rec.invoice_type == 'aging':
                #     commission = 0
                #     if not invoice.payment_ids:
                #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'againg without payment', 'commission':rec.id})
                #         continue
                #     line = invoice.sale_commission_ids.filtered(lambda r: r.id != rec.id and r.sale_person_id.id == rec.sale_person_id.id)
                #     if not line:
                #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'againg without main line', 'commission':rec.id})
                #         continue
                #     if len(line) > 1:
                #         line = line[0]
                #     payment_date = max([r.payment_date for r in invoice.payment_ids])
                #     if payment_date > invoice.date_due:
                #         extra_days = payment_date - invoice.date_due
                #         if invoice.partner_id.company_id.commission_ageing_ids:
                #             commission_ageing = invoice.partner_id.company_id.commission_ageing_ids.filtered(
                #                 lambda r: r.delay_days <= extra_days.days)
                #             commission_ageing = commission_ageing.sorted(key=lambda r: r.delay_days, reverse=True)
                #             if commission_ageing and commission_ageing[0].reduce_percentage:
                #                 commission = commission_ageing[0].reduce_percentage * line.commission / 100
                #     if round(rec.commission, 2) != round(commission, 2):
                #         # rec.write({'commission': commission})
                #         res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': 'aging commission difference', 'commission':rec.id, 'commission_s':rec.commission, 'commission_o': commission, 'profit':profit})
                #         continue
        return res

    def correct_aging_com(self, invoice_ids=[]):
        res = []
        for invoice in self.env['account.invoice'].browse(invoice_ids):
            print(invoice)
            try:
                invoice.sale_commission_ids.filtered(lambda r: r.invoice_type == 'aging').unlink()
                invoice.check_due_date(invoice.sale_commission_ids)
            except Exception as e:
                res.append({'invoice_id':invoice.id, 'number': invoice.number, 'exception': e})
        return res



    def correct_delivery_charge(self, order_ids=[]):
        for order in self.env['sale.order'].browse(order_ids):
            if not order.order_line.filtered(lambda rec: rec.is_delivery is True):
                order.adjust_delivery_line()
            invoice = order.invoice_ids[:1]

            if order.gross_profit != invoice.gross_profit and invoice.sale_commission_ids and invoice.state=='paid':
                profit = order.gross_profit
                # rule = rec.invoice_id.partner_id.commission_percentage_ids.filtered(lambda r: r.sale_person_id.id == rec.sale_person_id.id)
                # sales_person_ids = rec.invoice_id.partner_id.sales_person_ids
                for rec in invoice.sale_commission_ids:
                    rule = invoice.partner_id.commission_percentage_ids.filtered(lambda r: r.sale_person_id.id == rec.sale_person_id.id)
                    if not rule:
                        rec.commission = 0
                        continue
                    if rec.sale_person_id.id not in invoice.partner_id.sales_person_ids.ids:
                        rec.commission=0
                        rec.is_cancelled=True
                        continue
                    if profit <= 0:
                        if rule.rule_id.based_on == 'invoice' and rec.commission == 0:
                            amount = invoice.amount_total
                            commission = amount * (rule.rule_id.percentage / 100)
                            rec.commission = commission
                            logging.error(('******************---------------->', invoice))
                        else:
                            rec.commission = 0
                    commission = 0
                    if rule.rule_id.based_on in ['profit', 'profit_delivery']:
                        commission = profit * (rule.rule_id.percentage / 100)
                    if invoice.type == 'out_refund' and commission > 0:
                        commission = -commission
                    logging.error(('******************', order, order.gross_profit ,invoice, invoice.gross_profit, rec.commission, commission))
                    rec.commission = round(commission, 2)


    def correct_commission(self, partner_id=None):
        pending_ids = []
        if not len(self) and partner_id:
            self = self.search([('sale_person_id', '=', partner_id), ('invoice_id', '!=', False)])
        elif not len(self):
            self = self.search([('invoice_id', '!=', False)])
        for rec in self.filtered(lambda r: r.invoice_id):
            if rec.invoice_id:
                rule = rec.invoice_id.partner_id.commission_percentage_ids.filtered(lambda r: r.sale_person_id.id == rec.sale_person_id.id)
                if rule.rule_id.based_on not in ['profit', 'profit_delivery']:
                    continue
                commission = rec.invoice_id.gross_profit * (rule.rule_id.percentage / 100)
                if rec.invoice_type == 'bounced_cheque':
                    commission = commission * -1
                    rec.write({'commission': commission})
                    if rec.invoice_id.gross_profit <= 0:
                        rec.write({'commission': 0})

                elif rec.invoice_type == 'aging':
                    inv = rec.invoice_id.sale_commission_ids.filtered(lambda r: r.id != rec.id)
                    if len(inv) > 1:
                        pending_ids.append(rec.id)
                        continue
                    payment_date = max([payment.payment_date for payment in rec.invoice_id.payment_ids])
                    if payment_date > rec.invoice_id.date_due:
                        extra_days = payment_date - rec.invoice_id.date_due
                        if rec.invoice_id.partner_id.company_id.commission_ageing_ids:
                            commission_ageing = rec.invoice_id.partner_id.company_id.commission_ageing_ids.filtered(
                                lambda r: r.delay_days <= extra_days.days)
                            commission_ageing = commission_ageing.sorted(key=lambda r: r.delay_days, reverse=True)
                            if commission_ageing and commission_ageing[0].reduce_percentage:
                                commission = commission_ageing[0].reduce_percentage * inv.commission / 100

                                rec.write({'commission': -commission})
                                if rec.invoice_id.gross_profit <= 0:
                                    rec.write({'commission': 0})
                                    inv.write({'commission': 0})
                                    # rec.is_cancelled = True

                else:
                    rec.invoice_id.with_context({'is_cancelled':True}).check_commission(rec)
        logging.error('============================>error ids')
        logging.error(pending_ids)
        return True

    @api.depends('is_paid')
    def get_invoice_paid_date(self):
        for rec in self:
            if rec.is_paid:
                if rec.invoice_type in ('out_invoice', 'out_refund', 'aging'):
                    payment_date_list = [payment.payment_date for payment in rec.invoice_id.payment_ids]
                    rec.paid_date = max(payment_date_list) if payment_date_list else False
                elif rec.invoice_type in ('draw', 'bounced_cheque', 'cancel', 'unreconcile'):
                    rec.paid_date = rec.commission_date
    @api.multi
    def action_commission_remove(self):
        for rec in self:
            rec.settlement_id.message_post(
                body='Commission Line removed..!!<br/><span> Source &#8594; %s </span><br/>Amount &#8594; %0.2f' % (
                rec.invoice_id.move_name, rec.commission),
                subtype_id=self.env.ref('mail.mt_note').id)
            rec.is_removed = True

    @api.multi
    def action_commission_add(self):
        for rec in self:
            rec.settlement_id.message_post(
                body='Commission Line Added..!!<br/><span> Source &#8594; %s </span><br/>Amount &#8594; %0.2f' % (
                    rec.invoice_id.move_name, rec.commission),
                subtype_id=self.env.ref('mail.mt_note').id)
            rec.is_removed = False

    @api.model
    def create_weeekly_draw(self):
        draw_date = date.today()
        if draw_date.weekday() < 5:
            sales_persons = self.env['res.partner'].search([('is_sales_person', '=', True)])
            for sales_person in sales_persons:
                weekly_draw = sales_person.weekly_draw
                if weekly_draw and weekly_draw > 0:

                    daily_amount = float_round(weekly_draw / 5, precision_digits=2)
                    vals = {
                        'sale_person_id': sales_person.id,
                        'commission': -daily_amount,
                        'is_paid': True,
                        'invoice_type': 'draw',
                        'commission_date': date.today(),
                        'paid_date': date.today()
                    }
                    self.env['sale.commission'].create(vals)


SaleCommission()

class SalesCommission(models.Model):
    _name = 'sales.commission'
    _description = 'Sales Commission'

class SalesUnpaidCommission(models.Model):
    _name = 'sales.unpaid.commission'
    _description = 'Sale Unpaid Commission'

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
