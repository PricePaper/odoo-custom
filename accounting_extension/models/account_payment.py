# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from datetime import datetime, date

from odoo.exceptions import UserError
from odoo.tools.misc import formatLang, format_date


MAP_INVOICE_TYPE_PAYMENT_SIGN = {
    'out_invoice': 1,
    'in_refund': -1,
    'in_invoice': -1,
    'out_refund': 1,
}

class account_abstract_payment(models.AbstractModel):
    _inherit = "account.abstract.payment"

    @api.depends('invoice_ids', 'amount', 'payment_date', 'currency_id')
    def _compute_payment_difference(self):
        for pay in self.filtered(lambda p: p.invoice_ids):
            payment_amount = -pay.amount if pay.payment_type == 'outbound' else pay.amount
            flag = False
            for inv in pay.invoice_ids:
                days = (inv.date_invoice - fields.Date.context_today(inv)).days
                if inv.payment_term_id.is_discount and abs(days) < inv.payment_term_id.due_days and inv.type in ['out_invoice', 'in_invoice']:
                    flag = True
                    break
                elif inv.discount_from_batch:
                    flag = True
                    break
            currency = pay.currency_id

            pay.payment_difference = pay.with_context(exclude_discount=True)._compute_payment_amount(invoices=pay.invoice_ids, currency=currency) - payment_amount
            if pay.payment_type in ['inbound', 'outbound'] and flag:
                pay.writeoff_label = ','.join(pay.invoice_ids.mapped('payment_term_id').mapped('name'))
            elif pay.payment_difference:
                pay.writeoff_label = 'Discount'


    @api.multi
    def _compute_payment_amount(self, invoices=None, currency=None):
        # Get the payment invoices
        if not invoices:
            invoices = self.mapped('invoice_ids')

        # Get the payment currency
        payment_currency = currency
        if not payment_currency:
            payment_currency = self.currency_id or self.journal_id.currency_id or self.journal_id.company_id.currency_id or invoices and \
                               invoices[0].currency_id

        # Avoid currency rounding issues by summing the amounts according to the company_currency_id before
        invoice_datas = invoices.read_group(
            [('id', 'in', invoices.ids)],
            ['currency_id', 'type', 'residual_signed', 'residual_company_signed'],
            ['currency_id', 'type'], lazy=False)

        total = 0.0

        for invoice_data in invoice_datas:
            sign = MAP_INVOICE_TYPE_PAYMENT_SIGN[invoice_data['type']]
            amount_total = sign * invoice_data['residual_signed']
            amount_total_company_signed = sign * invoice_data['residual_company_signed']
            invoice_currency = self.env['res.currency'].browse(invoice_data['currency_id'][0])

            if payment_currency == invoice_currency:
                total += amount_total
            else:
                amount_total_company_signed = self.journal_id.company_id.currency_id._convert(
                    amount_total_company_signed,
                    payment_currency,
                    self.env.user.company_id,
                    self.payment_date or fields.Date.today()
                )
                total += amount_total_company_signed

        if not self._context.get('exclude_discount', False):
            for inv in self.invoice_ids:
                if inv.payment_term_id.is_discount:
                    days = (inv.date_invoice - fields.Date.context_today(inv)).days
                    if payment_currency == inv.currency_id:
                        invoice_amount = inv.residual
                    else:
                        invoice_amount = self.journal_id.company_id.currency_id._convert(
                            inv.residual,
                            payment_currency,
                            self.env.user.company_id,
                            self.payment_date or fields.Date.today()
                        )

                    if abs(days) < inv.payment_term_id.due_days:
                        discount = inv.payment_term_id.discount_per
                        if inv.type == 'out_invoice':
                            total = total - (invoice_amount * (discount / 100))
                        elif inv.type == 'in_invoice':
                            total = total + (invoice_amount * (discount / 100))
        return total

account_abstract_payment()

class AccountRegisterPayment(models.TransientModel):
    _inherit = "account.register.payments"

    payment_lines = fields.One2many('account.register.payment.lines', 'payment_id')
    writeoff_account_id = fields.Many2one('account.account', 'Discount Account')
    discount_amount = fields.Float('Total Discount Amount', compute="_get_discount")
    discount_total = fields.Float('Total', compute="_get_discount")
    payment_reference = fields.Char('Payment Reference')

    @api.model
    def _compute_payment_amount(self, invoices=None, currency=None):
        if not self.payment_lines:
            return super(AccountRegisterPayment, self)._compute_payment_amount(invoices, currency)

        invoices = invoices or self.invoice_ids
        amount = 0
        for line in self.payment_lines.filtered(lambda rec: rec.invoice_id.id in invoices.ids):
            amount += line.payment_amount
        return amount

    @api.depends("payment_lines.discounted_total", "payment_lines.discount")
    def _get_discount(self):
        """ Update total amount and discount"""
        if not self.payment_lines:
            return []

        amount, discount_amount = 0, 0
        for line in self.payment_lines:
            amount += line.payment_amount
            discount_amount += line.discount
        if not self.writeoff_account_id and discount_amount:
            invoice = self.payment_lines.mapped('invoice_id')
            invoice = invoice and invoice[0] or False
            if invoice:
                if invoice.type in ('out_invoice', 'out_refund'):
                    self.writeoff_account_id = invoice.company_id.discount_account_id
                else:
                    self.writeoff_account_id = invoice.company_id.purchase_writeoff_account_id
        self.amount = abs(amount)
        self.discount_amount = discount_amount
        self.discount_total = amount

    @api.model
    def default_get(self, fields):
        """Override to add payment lines and calculate discount"""
        context = dict(self._context or {})
        res = super(AccountRegisterPayment, self).default_get(fields)

        if context.get('active_model') != 'account.invoice':
            return res
        lines = []
        amount_total = 0
        wo_account = False
        discounted_total = 0
        flag = False
        invoices = self.env[context.get('active_model')].browse(context.get('active_ids'))
        res['group_invoices'] = True if len(invoices) > 1 else False
        for invoice in invoices:
            # get discount account from Company
            if any(inv.commercial_partner_id != invoices[0].commercial_partner_id for inv in invoices):
                raise UserError(_("In order to pay multiple invoices at once, they must belong to the same commercial partner."))
            if invoice.type in ('out_invoice', 'in_refund', 'out_refund'):
                wo_account = invoice.company_id.discount_account_id
                reference = invoice.origin
            else:
                wo_account = invoice.company_id.purchase_writeoff_account_id
                reference = invoice.reference
            discount_amount = 0
            discount = 0
            if invoice.payment_term_id.is_discount and not self._context.get('from_authorize', False):
                discount_days = invoice.payment_term_id.due_days
                if discount_days >= 0:
                    invoice_date = invoice.date_invoice
                    difference = (date.today() - invoice_date).days
                    if difference <= discount_days and invoice.payment_term_id.discount_per:
                        flag = True
                        discount = invoice.payment_term_id.discount_per or 1
                        discount_percentage = discount / 100
                        discount_amount = invoice.residual * discount_percentage
            discount_amount = round(discount_amount, 2)
            amount = invoice.residual_signed - discount_amount
            amount_total += amount
            discounted_total += discount_amount
            lines.append((0, 0, {
                'invoice_id': invoice.id,
                'discount': discount_amount,
                'discounted_total': amount,
                'amount_total': invoice.residual_signed,
                'currency_id': invoice.currency_id and invoice.currency_id.id,
                'discount_percentage': discount,
                'reference': reference,
                'invoice_date': invoice.date_invoice,
                'payment_amount': amount,
                'is_full_reconcile': True
            }))
        if flag:
            res.update({
                'payment_lines': lines,
                'writeoff_account_id': wo_account and wo_account.id or 0,
                'discount_amount': discounted_total,
                'payment_difference_handling': 'reconcile'
            })
        else:
            res.update({'payment_lines': lines})
        return res

    def get_payments_vals(self):
        """ Override to add payment lines and writeoff_account_id"""
        result = super(AccountRegisterPayment, self).get_payments_vals()
        for res in result:
            lines = []
            discount_amount = 0
            invoice_ids = res.get('invoice_ids', []) and res.get('invoice_ids', [])[0][2]
            for line in self.payment_lines.filtered(lambda rec: rec.invoice_id.id in invoice_ids):
                discount_amount += line.discount
                lines.append((0, 0, {
                    'invoice_id': line.invoice_id.id,
                    'discount': line.discount,
                    'discounted_total': line.discounted_total,
                    'discount_percentage': line.discount_percentage,
                    'reference': line.reference,
                    'invoice_date': line.invoice_date,
                    'payment_amount': line.payment_amount,
                    'is_full_reconcile': line.is_full_reconcile,
                    'amount_total': line.amount_total,
                }))
            res.update({'payment_reference': self.payment_reference, })
            if discount_amount and self.writeoff_account_id:
                res.update({'payment_difference_handling': 'reconcile',
                            'writeoff_account_id': self.writeoff_account_id.id,
                            'discount_amount': discount_amount,
                            })
            if lines:
                res.update({'payment_lines': lines})
        return result


AccountRegisterPayment()


class AccountRegisterPaymentLines(models.TransientModel):
    """
        New table to show payment lines and discount amount
    """
    _name = "account.register.payment.lines"
    _description = "Register Payment Lines"

    payment_id = fields.Many2one('account.register.payments', 'Payment')
    invoice_id = fields.Many2one('account.invoice', string='Invoice', required=True)
    amount_total = fields.Monetary('Invoice Amount', related='invoice_id.residual')
    currency_id = fields.Many2one('res.currency', 'Currency', related='invoice_id.currency_id')
    discounted_total = fields.Float('Actual Amount', compute="_get_discount_total")
    discount = fields.Float('Discount')
    discount_percentage = fields.Float('T.Disc(%)')
    reference = fields.Char(string="Reference")
    invoice_date = fields.Date('Invoice Date')
    payment_amount = fields.Float('Payment Amount')
    is_full_reconcile = fields.Boolean('Full')

    @api.depends('discount')
    def _get_discount_total(self):
        for line in self:
            if line.amount_total >= 0:
                line.discounted_total = line.amount_total - line.discount
            else:
                line.discounted_total = line.amount_total + line.discount

    @api.onchange("discount")
    def onchange_discount(self):
        if self.discount != 0:
            customer_discount_per = self.env['ir.config_parameter'].sudo().get_param('accounting_extension.customer_discount_limit', 5.00)
            if isinstance(customer_discount_per, str):
                customer_discount_per = float(customer_discount_per)
            discount_amount_limit = round(self.invoice_id.residual_signed * (customer_discount_per / 100), 2)
            if discount_amount_limit and discount_amount_limit < self.discount:
                raise UserError(_('Cannot add discount more than {}%.'.format(customer_discount_per)))
            if self.amount_total >= 0:
                self.payment_amount = self.amount_total - self.discount
            else:
                self.payment_amount = self.amount_total + self.discount
        else:
            if self.discounted_total != self.payment_amount:
                self.is_full_reconcile = False

    @api.onchange("payment_amount")
    def onchange_payment_amount(self):
        if self.payment_amount != self.discounted_total:
            self.is_full_reconcile = False
        else:
            self.is_full_reconcile = True

    @api.onchange("is_full_reconcile")
    def onchange_is_full_reconcile(self):
        if self.is_full_reconcile is True:
            self.payment_amount = self.amount_total - self.discount
        elif self.payment_amount == self.amount_total - self.discount:
            self.is_full_reconcile = True


AccountRegisterPaymentLines()


class AccountPayment(models.Model):
    _inherit = "account.payment"

    @api.depends("payment_lines")
    def _has_lines(self):
        for record in self:
            record.has_payment_lines = len(record.payment_lines) > 0 and True or False

    discount_amount = fields.Float('Discount Amount')
    payment_lines = fields.One2many('account.payment.lines', 'payment_id')
    has_payment_lines = fields.Boolean('Has Payment Lines?', compute="_has_lines")
    payment_reference = fields.Char('Payment Reference')

    @api.model
    def default_get(self, fields):
        """Override to add payment lines and calculate discount"""
        res = super(AccountPayment, self).default_get(fields)
        context = dict(self._context or {})

        if context.get('active_model') != 'account.invoice':
            return res

        discounted_total = 0
        wo_account = False
        flag = False
        for invoice in self.env[context.get('active_model')].browse(context.get('active_ids')):
            # get discount account from Company
            if invoice.type in ('out_invoice', 'in_refund'):
                wo_account = invoice.company_id.discount_account_id
            else:
                wo_account = invoice.company_id.purchase_writeoff_account_id
            discount_amount = 0
            if invoice.payment_term_id.is_discount and not self._context.get('from_authorize', False):
                discount_days = invoice.payment_term_id.due_days
                if discount_days >= 0:
                    invoice_date = invoice.date_invoice
                    now = date.today()
                    difference = (now - invoice_date).days

                    if difference <= discount_days and invoice.payment_term_id.discount_per:
                        flag = True
                        discount = invoice.payment_term_id.discount_per or 1
                        discount_percentage = discount / 100
                        discount_amount = invoice.residual * discount_percentage

            discounted_total += discount_amount

        if flag:
            res.update({
                'payment_difference_handling': 'reconcile',
                'writeoff_account_id': wo_account and wo_account.id or 0,
                'discount_amount': discounted_total
            })

        return res

    def _create_payment_entry(self, amount):

        """
            Override method to support partial payment and discount in lines
        """

        # check if there is any partial payment else super method will handle the things
        if self.has_payment_lines and self.payment_lines.filtered(lambda record: record.is_full_reconcile is False):

            aml_obj = self.env['account.move.line'].with_context(check_move_validity=False)
            invoice_currency = False
            if self.invoice_ids and all([x.currency_id == self.invoice_ids[0].currency_id for x in self.invoice_ids]):
                # if all the invoices selected share the same currency, record the payment in that currency too
                invoice_currency = self.invoice_ids[0].currency_id
            debit, credit, amount_currency, currency_id = aml_obj.with_context(
                date=self.payment_date)._compute_amount_fields(amount, self.currency_id, self.company_id.currency_id)

            move = self.env['account.move'].create(self._get_move_vals())
            # Write line corresponding to invoice payment
            counterpart_aml_dict = self._get_shared_move_line_vals(debit, credit, amount_currency, move.id, False)
            counterpart_aml_dict.update(self._get_counterpart_move_line_vals(self.invoice_ids))
            counterpart_aml_dict.update({'currency_id': currency_id})
            counterpart_aml = aml_obj.create(counterpart_aml_dict)
            # Reconcile with the invoices
            if self.payment_difference_handling == 'reconcile' and self.payment_difference:
                # add writeoff amount as current discount
                # check the sign if its suplier or cust refund then -ve
                payment_difference = self.discount_amount * (self.payment_type in ('outbound', 'transfer') and -1 or 1)
                writeoff_line = self._get_shared_move_line_vals(0, 0, 0, move.id, False)
                debit_wo, credit_wo, amount_currency_wo, currency_id = aml_obj.with_context(
                    date=self.payment_date)._compute_amount_fields(payment_difference, self.currency_id,
                                                                  self.company_id.currency_id)
                writeoff_line['name'] = _('Counterpart')
                writeoff_line['account_id'] = self.writeoff_account_id.id
                writeoff_line['debit'] = debit_wo
                writeoff_line['credit'] = credit_wo
                writeoff_line['amount_currency'] = amount_currency_wo
                writeoff_line['currency_id'] = currency_id
                writeoff_line = aml_obj.create(writeoff_line)
                if counterpart_aml['debit']:
                    counterpart_aml['debit'] += credit_wo - debit_wo
                if counterpart_aml['credit']:
                    counterpart_aml['credit'] += debit_wo - credit_wo
                counterpart_aml['amount_currency'] -= amount_currency_wo
                # get payments without partial
            reconciled_lines = self.payment_lines.filtered(lambda record: record.is_full_reconcile is True)
            # register the payment at ones
            reconciled_lines.mapped('invoice_id').register_payment(counterpart_aml)
            # if ther is any partial payment post invoices individually
            if self.payment_lines.filtered(lambda record: record.is_full_reconcile == False):
                amount_r = sum(reconciled_lines.mapped('payment_amount')) + sum(reconciled_lines.mapped('discount'))
                amount_r = amount_r * (self.payment_type in ('outbound', 'transfer') and 1 or -1)
                debit_r, credit_r, amount_currency_r, currency_id_r = aml_obj.with_context(
                    date=self.payment_date)._compute_amount_fields(amount_r, self.currency_id,
                                                                  self.company_id.currency_id)
                # chnage the journal lines amount with posted amount
                if amount_r:
                    if counterpart_aml['debit']:
                        counterpart_aml['debit'] = debit_r
                    if counterpart_aml['credit']:
                        counterpart_aml['credit'] = credit_r
                flag = False
                # loop through the partial payment lines
                for line in self.payment_lines.filtered(lambda record: record.is_full_reconcile is False):
                    amount_t = (line.payment_amount + line.discount) * (
                        self.payment_type in ('outbound', 'transfer') and 1 or -1)
                    # find the amount
                    debit_t, credit_t, amount_currency_t, currency_id_t = aml_obj.with_context(
                        date=self.payment_date)._compute_amount_fields(amount_t, self.currency_id,
                                                                      self.company_id.currency_id)
                    # if ther is no full reconciled lines then assign the aamount to move lines
                    # else append the current amount to existing amount
                    if not flag and not amount_r:
                        flag = True
                        counterpart_aml['debit'] = debit_t
                        counterpart_aml['credit'] = credit_t
                    else:
                        counterpart_aml['reconciled'] = False
                        if counterpart_aml['debit']:
                            counterpart_aml['debit'] += debit_t
                        if counterpart_aml['credit']:
                            counterpart_aml['credit'] += credit_t
                    line.invoice_id.register_payment(counterpart_aml)

            # Write counterpart lines
            if not self.currency_id != self.company_id.currency_id:
                amount_currency = 0
            liquidity_aml_dict = self._get_shared_move_line_vals(credit, debit, -amount_currency, move.id, False)
            liquidity_aml_dict.update(self._get_liquidity_move_line_vals(-amount))
            aml_obj.create(liquidity_aml_dict)
            move.post()
            return move
#
        # return super(AccountPayment, self)._create_payment_entry(amount)
        else:
            aml_obj = self.env['account.move.line'].with_context(check_move_validity=False)
            invoice_currency = False
            if self.invoice_ids and all([x.currency_id == self.invoice_ids[0].currency_id for x in self.invoice_ids]):
                #if all the invoices selected share the same currency, record the paiement in that currency too
                invoice_currency = self.invoice_ids[0].currency_id
            debit, credit, amount_currency, currency_id = aml_obj.with_context(date=self.payment_date)._compute_amount_fields(amount, self.currency_id, self.company_id.currency_id)

            move = self.env['account.move'].create(self._get_move_vals())

            #Write line corresponding to invoice payment
            counterpart_aml_dict = self._get_shared_move_line_vals(debit, credit, amount_currency, move.id, False)
            counterpart_aml_dict.update(self._get_counterpart_move_line_vals(self.invoice_ids))
            counterpart_aml_dict.update({'currency_id': currency_id})
            counterpart_aml = aml_obj.create(counterpart_aml_dict)

            #Reconcile with the invoices
            if self.payment_difference_handling == 'reconcile' and self.payment_difference:
                writeoff_line = self._get_shared_move_line_vals(0, 0, 0, move.id, False)
                amount_currency_wo, currency_id = aml_obj.with_context(date=self.payment_date)._compute_amount_fields(self.payment_difference, self.currency_id, self.company_id.currency_id)[2:]
                # the writeoff debit and credit must be computed from the invoice residual in company currency
                # minus the payment amount in company currency, and not from the payment difference in the payment currency
                # to avoid loss of precision during the currency rate computations. See revision 20935462a0cabeb45480ce70114ff2f4e91eaf79 for a detailed example.
                total_residual_company_signed = sum(invoice.residual_company_signed for invoice in self.invoice_ids)
                total_payment_company_signed = self.currency_id.with_context(date=self.payment_date).compute(self.amount, self.company_id.currency_id)
                # if all(inv.type in ['in_invoice', 'out_refund'] for inv in self.invoice_ids):#self.invoice_ids[0].type in ['in_invoice', 'out_refund']:
                #     amount_wo = total_payment_company_signed - total_residual_company_signed
                # else:
                #     amount_wo = total_residual_company_signed - total_payment_company_signed
                if any(inv.type in ['in_invoice'] for inv in self.invoice_ids): #self.invoice_ids[0].type == 'in_invoice':
                    amount_wo = total_payment_company_signed - total_residual_company_signed
                elif all(inv.type in ['in_refund'] for inv in self.invoice_ids): #self.invoice_ids[0].type == 'in_refund':
                    amount_wo = - total_payment_company_signed - total_residual_company_signed
                elif all(inv.type in ['out_refund'] for inv in self.invoice_ids): #self.invoice_ids[0].type == 'out_refund':
                    amount_wo = total_payment_company_signed + total_residual_company_signed
                else:
                    amount_wo = total_residual_company_signed - total_payment_company_signed
                # Align the sign of the secondary currency writeoff amount with the sign of the writeoff
                # amount in the company currency
                if amount_wo > 0:
                    debit_wo = amount_wo
                    credit_wo = 0.0
                    amount_currency_wo = abs(amount_currency_wo)
                else:
                    debit_wo = 0.0
                    credit_wo = -amount_wo
                    amount_currency_wo = -abs(amount_currency_wo)
                writeoff_line['name'] = self.writeoff_label
                writeoff_line['account_id'] = self.writeoff_account_id.id
                writeoff_line['debit'] = debit_wo
                writeoff_line['credit'] = credit_wo
                writeoff_line['amount_currency'] = amount_currency_wo
                writeoff_line['currency_id'] = currency_id
                writeoff_line = aml_obj.create(writeoff_line)
                if counterpart_aml['debit'] or (writeoff_line['credit'] and not counterpart_aml['credit']):
                    counterpart_aml['debit'] += credit_wo - debit_wo
                if counterpart_aml['credit'] or (writeoff_line['debit'] and not counterpart_aml['debit']):
                    counterpart_aml['credit'] += debit_wo - credit_wo
                counterpart_aml['amount_currency'] -= amount_currency_wo

            #Write counterpart lines
            if not self.currency_id.is_zero(self.amount):
                if not self.currency_id != self.company_id.currency_id:
                    amount_currency = 0
                liquidity_aml_dict = self._get_shared_move_line_vals(credit, debit, -amount_currency, move.id, False)
                liquidity_aml_dict.update(self._get_liquidity_move_line_vals(-amount))
                aml_obj.create(liquidity_aml_dict)

            #validate the payment
            move.post()

            #reconcile the invoice receivable/payable line(s) with the payment
            self.invoice_ids.register_payment(counterpart_aml)

            return move

    def _check_build_page_info(self, i, p):
        result = super(AccountPayment, self)._check_build_page_info(i, p)
        result.update({'have_bills': self.payment_type == 'outbound'})
        return result

    def _check_make_stub_line(self, invoice):
        """ Return the dict used to display an invoice/refund in the stub
        """
        result = super(AccountPayment, self)._check_make_stub_line(invoice)
        discount = sum(self.env['account.payment.lines'].search([('invoice_id', '=', invoice.id)]).mapped('discount'))
        if not discount and self.discount_amount:
            discount = self.discount_amount
        result.update({'discount': formatLang(self.env, discount, currency_obj=invoice.currency_id)})
        if discount:
            if invoice.type in ['in_invoice', 'out_refund']:
                invoice_sign = 1
                invoice_payment_reconcile = invoice.move_id.line_ids.mapped('matched_debit_ids').filtered(lambda r: r.debit_move_id in self.move_line_ids)
            else:
                invoice_sign = -1
                invoice_payment_reconcile = invoice.move_id.line_ids.mapped('matched_credit_ids').filtered(lambda r: r.credit_move_id in self.move_line_ids)

            if self.currency_id != self.journal_id.company_id.currency_id:
                amount_paid = abs(sum(invoice_payment_reconcile.mapped('amount_currency')))
            else:
                amount_paid = abs(sum(invoice_payment_reconcile.mapped('amount')))

            result.update({'amount_paid': formatLang(self.env, (invoice_sign * amount_paid) - discount, currency_obj=invoice.currency_id)})
        return result


AccountPayment()


class AccountPaymentLines(models.Model):
    _name = "account.payment.lines"
    _description = "Payment Lines"

    payment_id = fields.Many2one('account.payment', 'Payment')
    invoice_id = fields.Many2one('account.invoice', string='Invoice', required=True)
    amount_total = fields.Monetary('Invoice Amount')
    currency_id = fields.Many2one('res.currency', 'Currency', related='invoice_id.currency_id')
    discounted_total = fields.Float('Actual Amount')
    discount = fields.Float('Discount')
    discount_percentage = fields.Float('T.Disc(%)')
    reference = fields.Char(string="Reference")
    invoice_date = fields.Datetime('Invoice Date')
    payment_amount = fields.Float('Payment Total')
    is_full_reconcile = fields.Boolean('Full')


AccountPaymentLines()
