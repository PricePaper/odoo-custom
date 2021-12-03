# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
from pprint import pprint
import json

from odoo.tools import float_compare


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    picking_ids = fields.Many2many('stock.picking', compute='_compute_picking_ids', string='Pickings')
    wrtoff_discount = fields.Float(string='Discount($)')
    has_outstanding = fields.Boolean(compute='_get_outstanding_info_JSON', groups="account.group_account_invoice", search='_search_has_outstanding')
    out_standing_credit = fields.Float(compute='_compute_out_standing_credit', string="Out Standing")
    discount_type = fields.Selection([('percentage', 'Discount(%)'), ('amount', 'Discount($)')], default='percentage')

    @api.depends('invoice_line_ids.profit_margin', 'wrtoff_discount', 'discount_from_batch')
    def calculate_gross_profit(self):
        """
        Compute the gross profit in invoice.
        """
        for invoice in self:
            if invoice.state == 'paid':
                gross_profit = 0
                for line in invoice.invoice_line_ids:
                    gross_profit += line.profit_margin
                if invoice.payment_ids and invoice.payment_ids.filtered(lambda r:r.payment_method_id.code == 'credit_card'):
                    card_amount = 0
                    for payment in invoice.payment_ids.filtered(lambda r:r.payment_method_id.code == 'credit_card'):
                        card_amount += payment.amount
                    gross_profit -= card_amount * 0.03
                if invoice.wrtoff_discount:
                    if invoice.discount_type == 'percentage':
                        gross_profit -= invoice.amount_total * invoice.wrtoff_discount / 100
                    else:
                        gross_profit -= invoice.wrtoff_discount
                if invoice.discount_from_batch:
                    gross_profit -= invoice.discount_from_batch
                if invoice.type == 'out_refund':
                    if gross_profit < 0:
                        gross_profit = 0
                invoice.update({'gross_profit': round(gross_profit, 2)})

            else:
                super(AccountInvoice, self).calculate_gross_profit()

    def _compute_out_standing_credit(self):
        for rec in self:
            info = json.loads(rec.outstanding_credits_debits_widget)
            rec.out_standing_credit = sum(list(map(lambda r: r['amount'], info['content']))) if info else 0

    @api.multi
    def action_invoice_cancel(self):
        if self._context.get('from_invoice_cancel_rpc', False):
            return super(AccountInvoice, self).action_invoice_cancel()
        if all([inv.type in ('in_invoice', 'in_refund') for inv in self]) and all([inv.state == 'draft' for inv in self]):
            return super(AccountInvoice, self).action_invoice_cancel()
        for invoice in self:
            if invoice.mapped('picking_ids').filtered(lambda r:r.state in ('in_transit', 'done')):
                raise ValidationError(_('Cannot perform this action, DO is in transit or done state'))
        if not self.env.user.has_group('account.group_account_manager') or not self.env.user.has_group('sales_team.group_sale_manager'):
            raise ValidationError(_('You dont have permissions to cancel an open invoice. Only Accounting adviser have the permission.'))

        return super(AccountInvoice, self).action_invoice_cancel()


    @api.multi
    def _search_has_outstanding(self, operator, value):
        if self._context.get('type') in ('out_invoice', 'in_refund'):
            account = self.env.user.company_id.partner_id.property_account_receivable_id.id
        else:
            account = self.env.user.company_id.partner_id.property_account_payable_id.id
        domain = [
            ('account_id', '=', account),
            ('reconciled', '=', False),
            ('move_id.state', '=', 'posted'),
            '|',
            '&', ('amount_residual_currency', '!=', 0.0), ('currency_id', '!=', None),
            '&', ('amount_residual_currency', '=', 0.0), '&', ('currency_id', '=', None),
            ('amount_residual', '!=', 0.0)]
        if self._context.get('type') in ('out_invoice', 'in_refund'):
            domain.extend([('credit', '>', 0), ('debit', '=', 0)])
        else:
            domain.extend([('credit', '=', 0), ('debit', '>', 0)])
        ids = self.env['account.move.line'].search(domain).mapped('partner_id').ids
        return [('partner_id', 'in', ids), ('state', 'in', ['open', 'in_payment'])]


    @api.depends('invoice_line_ids.stock_move_ids.picking_id')
    def _compute_picking_ids(self):
        for rec in self:
            rec.picking_ids = rec.invoice_line_ids.mapped('stock_move_ids').mapped('picking_id')

    @api.multi
    def name_get(self):
        result = []
        if self._context.get('from_batch_payment', False):
            for invoice in self:
                result.append((invoice.id, '%s ( %s )' % (invoice.number, invoice.residual)))
            return result
        return super(AccountInvoice, self).name_get()

    @api.multi
    def action_view_picking(self):
        action = self.env.ref('stock.action_picking_tree_all').read()[0]

        pickings = self.mapped('picking_ids')
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['res_id'] = pickings.id
        return action

    def remove_zero_qty_line(self):
        for invoice in self:
            for line in invoice.invoice_line_ids:
                if line.quantity == 0:
                    line.sudo().unlink()
            delivery_inv_lines = invoice.env['account.invoice.line']
            # if a invoice have only one line we need to make sure it's not a delivery charge.
            # if its a delivery charge, remove it from invoice.
            if len(invoice.invoice_line_ids) == 1 and invoice.invoice_line_ids.mapped('sale_line_ids'):
                if all(invoice.invoice_line_ids.mapped('sale_line_ids').mapped('is_delivery')):
                    delivery_inv_lines |= invoice.invoice_line_ids
            if delivery_inv_lines:
                delivery_inv_lines.sudo().unlink()

    @api.multi
    def action_invoice_open(self):

        if self:
            for invoice in self:
                invoice.remove_zero_qty_line()
                # for line in invoice.invoice_line_ids:
                #     if line.quantity == 0:
                #         line.sudo().unlink()
                # delivery_inv_lines = self.env['account.invoice.line']
                # # if a invoice have only one line we need to make sure it's not a delivery charge.
                # # if its a delivery charge, remove it from invoice.
                # if len(invoice.invoice_line_ids) == 1 and invoice.invoice_line_ids.mapped('sale_line_ids'):
                #     if all(invoice.invoice_line_ids.mapped('sale_line_ids').mapped('is_delivery')):
                #         delivery_inv_lines |= invoice.invoice_line_ids
                # if delivery_inv_lines:
                #     delivery_inv_lines.sudo().unlink()
            stock_picking = self.env['stock.picking']
            if  self.mapped('picking_ids').filtered(lambda pick: pick.state == 'cancel'):
                raise UserError(_('There is a Cancelled Picking linked to this invoice.'))
            for pick in self.mapped('picking_ids').filtered(lambda pick: pick.state != 'done'):
                move_info = pick.move_ids_without_package.filtered(lambda m: m.quantity_done < m.product_uom_qty)
                if move_info.ids:
                    stock_picking |= pick
                else:
                    pick.action_done()
            wiz = self.env['stock.backorder.confirmation'].create({'pick_ids': [(4, p.id) for p in stock_picking]})
            wiz.process_cancel_backorder()
            orders = self.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')
            for order in orders:
                picking = order.mapped('picking_ids')
                pending_picking = picking.filtered(lambda r: r.state not in ('done', 'cancel'))
                if not pending_picking and not order.storage_contract:
                    order.action_done()
        res = super(AccountInvoice, self).action_invoice_open()
        if not self:
            return res
        return res

    @api.model
    def default_get(self,default_fields):
        result = super(AccountInvoice, self).default_get(default_fields)
        result['date_invoice'] = fields.Date.today()
        return result

    @api.model
    def create(self, vals):
        invoice = super(AccountInvoice, self).create(vals)
        if not invoice.move_name or not invoice.number:
            if invoice.journal_id and invoice.journal_id.sequence_id:
                journal = invoice.journal_id
                sequence = journal.sequence_id
                if invoice and invoice.type in ['out_refund', 'in_refund'] and journal.refund_sequence:
                    if not journal.refund_sequence_id:
                        raise UserError(_('Please define a sequence for the credit notes'))
                    sequence = journal.refund_sequence_id
                new_name = sequence.with_context(ir_sequence_date=invoice.date_invoice or fields.Date.today()).next_by_id()
                invoice.write({'number': new_name, 'move_name': new_name})
        return invoice

    @api.multi
    def action_invoice_sent(self):
        self.ensure_one()
        template = self.env.ref('account.email_template_edi_invoice', False)
        report_template = self.env.ref('batch_delivery.ppt_account_selected_invoices_with_payment_report')
        if template and report_template and template.report_template.id != report_template.id:
            template.write({'report_template': report_template.id})
        return super(AccountInvoice, self).action_invoice_sent()

    def action_show_discount_popup(self):
        return {
            'name': 'Customer Discount',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.invoice',
            'res_id': self.id,
            'view_id': self.env.ref('batch_delivery.view_writeoff_discount_window_view_form').id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    def create_discount_writeoff(self):
        batch_discount = self._context.get('batch_discount', False)
        self.ensure_one()
        rev_line_account = self.partner_id and self.partner_id.property_account_receivable_id
        pay_line_account = self.partner_id and self.partner_id.property_account_payable_id
        if not rev_line_account:
            rev_line_account = self.env['ir.property'].\
                with_context(force_company=self.company_id.id).get('property_account_receivable_id', 'res.partner')
        if not pay_line_account:
            pay_line_account = self.env['ir.property'].\
                with_context(force_company=self.company_id.id).get('property_account_payable_id', 'res.partner')

        wrtf_account = self.company_id.purchase_writeoff_account_id if self.type == 'in_invoice' else self.company_id.discount_account_id
        company_currency = self.company_id.currency_id

        if not wrtf_account:
            raise UserError(_('Please set a discount account in company.'))
        customer_discount_per = self.env['ir.config_parameter'].sudo().get_param('accounting_extension.customer_discount_limit', 5.00)
        if isinstance(customer_discount_per, str):
            customer_discount_per = float(customer_discount_per)

        discount_limit = self.amount_total * (customer_discount_per / 100)
        writeoff_discount = self.discount_from_batch if batch_discount else self.wrtoff_discount

        if self.type == 'out_invoice' and (self.discount_type == 'amount' and writeoff_discount > discount_limit or self.discount_type == 'percentage' and writeoff_discount > customer_discount_per and not batch_discount):
            raise UserError(_('Invoices can not be discounted that much. Create a credit memo instead.'))

        discount = writeoff_discount if self.discount_type == 'amount' or batch_discount else self.amount_total * (writeoff_discount / 100)

        if float_compare(discount, self.residual, precision_digits=2) > 0:
            raise UserError(_('Cannot add discount more than residual $ %.2f' % self.residual))

        amobj = self.env['account.move'].create({
            'company_id': self.company_id.id,
            'date': fields.Date.today(),
            'journal_id': self.journal_id.id,
            'ref': self.reference,
            'line_ids': [(0, 0, {
                'account_id': pay_line_account.id if self.type == 'in_invoice' else rev_line_account.id ,
                'company_currency_id': company_currency.id,
                'credit': 0.0 if self.type == 'in_invoice' else discount,
                'debit': discount if self.type == 'in_invoice' else 0.0,
                'journal_id': self.journal_id.id,
                'name': 'Discount',
                'partner_id': self.partner_id.id
            }), (0, 0, {
                'account_id': wrtf_account.id,
                'company_currency_id': company_currency.id,
                'credit': discount if self.type == 'in_invoice' else 0.0,
                'debit': 0.0 if self.type == 'in_invoice' else discount,
                'journal_id': self.journal_id.id,
                'name': 'Discount',
                'partner_id': self.partner_id.id
             })]
        })
        if not self._context.get('force_stop'):
            amobj.post()
            rcv_lines = self.move_id.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
            rcv_wrtf = amobj.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
            (rcv_lines + rcv_wrtf).reconcile()
        return amobj


AccountInvoice()


class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    stock_move_ids = fields.Many2many('stock.move', string="Stock Moves")
    line_number = fields.Integer()


AccountInvoiceLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
