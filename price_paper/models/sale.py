# -*- coding: utf-8 -*-

import time
from datetime import datetime, date
from datetime import timedelta
from collections import Counter
import pytz
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import ValidationError, UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare, float_is_zero
from odoo.tools import float_round


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    release_date = fields.Date(string="Earliest Delivery Date", copy=False,
                               default=lambda s: s.get_release_deliver_default_date())
    customer_code = fields.Char(string='Partner Code', related='partner_id.customer_code')
    deliver_by = fields.Date(string="Deliver By", copy=False, default=lambda s: s.get_release_deliver_default_date())
    is_creditexceed = fields.Boolean(string="Credit limit exceeded", default=False, copy=False)
    is_low_price = fields.Boolean(string="Is Low Price", default=False, copy=False)
    credit_warning = fields.Text(string='Credit Limit Warning Message', compute='compute_credit_warning', copy=False)
    low_price_warning = fields.Text(string='Low Price Warning Message', compute='compute_credit_warning', copy=False)
    ready_to_release = fields.Boolean(string="Ready to release credit hold", default=False, copy=False)
    release_price_hold = fields.Boolean(string="Ready to release Price hold", default=False, copy=False)
    gross_profit = fields.Monetary(compute='calculate_gross_profit', string='Predicted Profit')
    is_quotation = fields.Boolean(string="Create as Quotation", default=False, copy=False)
    profit_final = fields.Monetary(string='Profit')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Draft Order Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Locked'),
        ('released', 'Released'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True, track_visibility='onchange', track_sequence=3,
        default='draft')
    storage_contract = fields.Boolean(string="Storage Product", default=False, copy=True)
    total_volume = fields.Float(string="Total Order Volume", compute='_compute_total_weight_volume')
    total_weight = fields.Float(string="Total Order Weight", compute='_compute_total_weight_volume')
    total_qty = fields.Float(string="Total Order Quantity", compute='_compute_total_weight_volume')
    sc_po_done = fields.Boolean(copy=False)
    show_contract_line = fields.Boolean(compute='_compute_show_contract_line', store=False)
    hold_state = fields.Selection(
        [('credit_hold', 'Credit Hold'),
         ('price_hold', 'Price hold'),
         ('both_hold', 'Price, Credit Hold'),
         ('release', 'Order Released')],
        string='Hold Status', default=False, copy=False)
    invoice_address_id = fields.Many2one('res.partner', string="Billing Address")
    sc_child_order_count = fields.Integer(compute='_compute_sc_child_order_count')

    def _compute_sc_child_order_count(self):
        for order in self:
            order.sc_child_order_count = len(order.order_line.mapped('storage_contract_line_ids.order_id'))

    @api.depends('state', 'order_line.invoice_status', 'order_line.invoice_lines')
    def _get_invoiced(self):
        super(SaleOrder, self)._get_invoiced()
        for order in self:
            if order.storage_contract and order.state in ['done', 'released']:
                if any([l.invoice_status == 'to invoice' for l in order.order_line if not l.is_downpayment]):
                    order.invoice_status = 'to invoice'
                elif all([l.invoice_status == 'invoiced' for l in order.order_line if not l.is_downpayment]):
                    order.invoice_status = 'invoiced'
                elif all([l.invoice_status == 'upselling' for l in order.order_line if not l.is_downpayment]):
                    order.invoice_status = 'upselling'
                else:
                    order.invoice_status = 'no'

    @api.multi
    def make_done_orders(self):
        # orders = self.env['sale.order'].search([('state', '=', 'sale'), ('invoice_status', '=', 'invoiced')])
        for order in self:
            picking_status = order.picking_ids.mapped('state')
            invoice_state = order.invoice_ids.mapped('state')
            if picking_status and any(state not in ('done', 'cancel') for state in picking_status):
                continue
            if invoice_state and any(state in ('draft') for state in invoice_state):
                continue
            order.action_done()
        return True

    @api.depends('partner_id')
    def _compute_show_contract_line(self):
        for order in self:
            if order.partner_id:
                count = self.env['sale.order.line'].search_count([
                    ('order_partner_id', '=', order.partner_id.id),
                    ('storage_remaining_qty', '>', 0),
                    ('order_id.state', '=', 'released')])
                order.show_contract_line = bool(count)

    @api.depends('order_line.product_id', 'order_line.product_uom_qty')
    def _compute_total_weight_volume(self):
        for order in self:
            volume = 0
            weight = 0
            qty = 0
            for line in order.order_line:
                if not line.is_delivery:
                    volume += line.gross_volume
                    weight += line.gross_weight
                    qty += line.product_uom_qty

            order.total_volume = volume
            order.total_weight = weight
            order.total_qty = qty

    @api.multi
    def confirm_multiple_orders(self, records):
        msg = ''
        for rec in records:
            if rec.state != 'draft':
                raise UserError(_(
                    "Some of the selected Orders are not in draft state"))
            res = rec.action_confirm()
            if res and res != True and res.get('context') and res.get('context').get('warning_message'):
                msg = msg + '\n' + rec.name + '\n' + res.get('context').get('warning_message')
        if msg:
            msg = "Some of the selected Orders are on HOLD." + '\n' + msg
            raise UserError(_(msg))

    @api.multi
    def action_cancel(self):

        for sale_order in self:
            sale_order.is_creditexceed = False
            sale_order.is_low_price = False
            sale_order.ready_to_release = False
            sale_order.release_price_hold = False
            sale_order.hold_state = False

            if sale_order.storage_contract:
                sale_order.order_line.mapped('purchase_line_ids.order_id').button_cancel()

        return super(SaleOrder, self).action_cancel()

    @api.multi
    def _create_storage_downpayment_invoice(self, order, so_lines):
        """
        Create invoice for storage contract product down payment
        """

        inv_obj = self.env['account.invoice']
        ir_property_obj = self.env['ir.property']

        context = {'lang': order.partner_id.lang}
        name = _('Down Payment')
        del context
        invoice_line_ids = []
        for line in so_lines:

            taxes = line.product_id.taxes_id.filtered(
                lambda r: not order.company_id or r.company_id == order.company_id)
            if order.fiscal_position_id and taxes:
                tax_ids = order.fiscal_position_id.map_tax(taxes, line.product_id, order.partner_shipping_id).ids
            else:
                tax_ids = taxes.ids
            account_id = False
            if line.product_id.id:
                account_id = order.fiscal_position_id.map_account(line.product_id.storage_contract_account_id).id
            if not account_id:
                raise UserError(
                    _(
                        'There is no storage income account defined for this product: "%s". You may have to install a chart of account from Accounting app, settings menu.') %
                    (line.product_id.name,))
            invoice_line = (0, 0, {
                'name': name,
                'origin': order.name,
                'account_id': account_id,
                'price_unit': line.price_unit,
                'quantity': 1.0,
                'discount': 0.0,
                'uom_id': line.product_id.uom_id.id,
                'product_id': line.product_id.id,
                'sale_line_ids': [(6, 0, [line.id])],
                'invoice_line_tax_ids': [(6, 0, tax_ids)],
                'analytic_tag_ids': [(6, 0, line.analytic_tag_ids.ids)],
                'account_analytic_id': order.analytic_account_id.id or False,
            })
            invoice_line_ids.append(invoice_line)

        invoice = inv_obj.create({
            'name': order.client_order_ref or order.name,
            'origin': order.name,
            'type': 'out_invoice',
            'reference': False,
            'storage_down_payment': True,
            'account_id': order.partner_id.property_account_receivable_id.id,
            'partner_id': order.partner_invoice_id.id,
            'partner_shipping_id': order.partner_shipping_id.id,
            'invoice_line_ids': invoice_line_ids,
            'currency_id': order.pricelist_id.currency_id.id,
            'payment_term_id': order.payment_term_id.id,
            'fiscal_position_id': order.fiscal_position_id.id or order.partner_id.property_account_position_id.id,
            'team_id': order.team_id.id,
            'user_id': order.user_id.id,
            'comment': order.note,
        })
        invoice.compute_taxes()
        invoice.message_post_with_view('mail.message_origin_link',
                                       values={'self': invoice, 'origin': order},
                                       subtype_id=self.env.ref('mail.mt_note').id)
        return invoice

    @api.multi
    def action_create_open_invoice_xmlrpc(self, invoice_date):
        sale_amount = self.amount_total or 0
        invoice_amount = round(sum(rec.amount_total_signed for rec in self.invoice_ids) or 0.0, 2)
        data = {'sale_amount': sale_amount, 'invoice_amount': invoice_amount}
        if sale_amount == invoice_amount or sale_amount == -invoice_amount:
            return self.invoice_ids and self.invoice_ids.ids or False, data
        else:
            self.action_invoice_create(final=True)
            self.invoice_ids.write({'move_name': self.note, 'date_invoice': invoice_date or False})
            self.invoice_ids.action_invoice_open()
            invoice_amount = sum(rec.amount_total for rec in self.invoice_ids) or 0
            data = {'sale_amount': sale_amount, 'invoice_amount': invoice_amount}
            return self.invoice_ids.ids, data

    @api.multi
    def import_draft_invoice(self, data):

        if self.invoice_ids:
            sale_amount = self.amount_total or 0
            invoice_amount = sum(rec.amount_total for rec in self.invoice_ids) or 0
            res = {'sale_amount': sale_amount, 'invoice_amount': invoice_amount}
            return res

        missing_msg = ''

        picking_ids = self.picking_ids
        move_lines = self.picking_ids.mapped('move_line_ids')
        picking_ids.is_transit = True
        picking_ids.move_ids_without_package.write({'is_transit': True})
        for line in data['do_lines']:
            product_id = line.get('product_id')
            product_uom_qty = line.get('quantity_ordered')
            qty_done = line.get('quantity_shipped')
            if qty_done != 0:
                move_line = move_lines.filtered(lambda r: r.product_id.id == product_id)
                if move_line:
                    move_line.qty_done = qty_done
                    move_line.move_id.sale_line_id.qty_delivered = qty_done
                else:
                    missing_msg += 'Invoice : ' + data.get('name') + ' Product_id : ' + str(product_id) + '\n'
        delivery_line = self.order_line.filtered(lambda r: r.product_id.default_code == 'misc')
        if delivery_line:
            delivery_line.qty_delivered_method = 'manual'
            delivery_line.qty_delivered_manual = 1
        if missing_msg:
            return {'missing_msg': missing_msg}

        res = self.action_invoice_create(final=True)
        invoice = self.env['account.invoice'].browse(res)
        invoice.write({'move_name': data.get('name'), 'date_invoice': data.get('date')})
        picking_ids.write({'is_invoiced': True})
        sale_amount = self.amount_total or 0
        invoice_amount = sum(rec.amount_total for rec in self.invoice_ids) or 0
        res = {'sale_amount': sale_amount, 'invoice_amount': invoice_amount, 'missing_msg': missing_msg}

        return res

    @api.multi
    def action_create_order_line_xmlrpc(self, vals):
        order_line = self.env['sale.order.line'].create(vals)
        order_line.qty_delivered_method = 'manual'
        order_line.qty_delivered_manual = vals.get('qty_delivered_manual')
        order_line.qty_to_invoice = vals.get('qty_delivered_manual')
        return order_line.id

    @api.multi
    def fix_for_do(self):
        self.action_cancel()
        self.action_draft()
        self.action_confirm()
        return True

    @api.multi
    def action_create_storage_do(self):
        """
        create purchase order for storage contract
        """
        self.run_storage()
        self.write({'sc_po_done': True})

    @api.multi
    def action_release(self):
        self.write({'state': 'released'})

    @api.multi
    def action_restore(self):
        return self.write({'state': 'done'})

    # @api.multi
    # def action_create_storage_downpayment(self):
    #     """
    #     Create invoice for storage contract product down payment
    #     """
    #
    #     sale_line_obj = self.env['sale.order.line']
    #     for order in self:
    #         storage_pr = order.company_id.storage_product_id
    #         if not storage_pr:
    #             raise UserError('Please set a storage product in company.')
    #         taxes = storage_pr.taxes_id.filtered(lambda r: not order.company_id or r.company_id == order.company_id)
    #         if order.fiscal_position_id and taxes:
    #             tax_ids = order.fiscal_position_id.map_tax(taxes, storage_pr, order.partner_shipping_id).ids
    #         else:
    #             tax_ids = taxes.ids
    #         so_lines = order.order_line.filtered(lambda r: r.is_downpayment)
    #         if not so_lines:
    #             so_lines = sale_line_obj.create({
    #                 'name': _('Advance: %s') % (time.strftime('%m %Y'),),
    #                 'price_unit': order.amount_total,
    #                 'product_uom_qty': 0.0,
    #                 'order_id': order.id,
    #                 'discount': 0.0,
    #                 'product_uom': storage_pr.uom_id.id,
    #                 'product_id': storage_pr.id,
    #                 'tax_id': [(6, 0, tax_ids)],
    #                 'is_downpayment': True,
    #             })
    #         else:
    #             so_lines.write({'price_unit': order.amount_total})
    #         self._create_storage_downpayment_invoice(order, so_lines)
    #         order.sc_payment_done = True
    #     return True

    @api.depends('picking_policy')
    def _compute_expected_date(self):
        super(SaleOrder, self)._compute_expected_date()
        for order in self:
            dates_list = []
            confirm_date = fields.Datetime.from_string((order.confirmation_date or order.write_date) if order.state in (
                'sale', 'done') else fields.Datetime.now())
            for line in order.order_line.filtered(lambda x: x.state != 'cancel' and not x._is_delivery()):
                dt = confirm_date + timedelta(days=line.customer_lead or 0.0)
                dates_list.append(dt)
            if dates_list:
                expected_date = min(dates_list) if order.picking_policy == 'direct' else max(dates_list)
                order.expected_date = fields.Datetime.to_string(expected_date)

    @api.multi
    def action_fax_send(self):
        '''
        This function opens a window to compose an email, with the edi sale template message loaded by default
        '''
        self.ensure_one()
        ir_model_data = self.env['ir.model.data']
        try:
            template_id = ir_model_data.get_object_reference('price_paper', 'fax_template_edi_sale')[1]
        except ValueError:
            template_id = False
        if not self.partner_id.fax_number:
            raise ValidationError(_('Please enter customer Fax number first.'))
        email_to = self.partner_id.fax_number + '@efaxsend.com'
        email_context = self.env.context.copy()
        email_context.update({
            'email_to': email_to,
            'recipient_ids': ''
        })
        template = self.env['mail.template'].browse(template_id)
        return template.with_context(email_context).send_mail(self.id)

    @api.model
    def get_release_deliver_default_date(self):
        user_tz = self.env.user.tz or "UTC"
        user_time = datetime.now(pytz.timezone(user_tz)).date()
        user_time = user_time + relativedelta(days=1)
        return user_time

    @api.onchange('partner_shipping_id')
    def onchange_partner_id_carrier_id(self):
        if self.partner_shipping_id:
            shipping_date = date.today() + relativedelta(days=1)
            day_list = []
            if self.partner_shipping_id.change_delivery_days:
                if self.partner_shipping_id.delivery_day_mon:
                    day_list.append(0)
                if self.partner_shipping_id.delivery_day_tue:
                    day_list.append(1)
                if self.partner_shipping_id.delivery_day_wed:
                    day_list.append(2)
                if self.partner_shipping_id.delivery_day_thu:
                    day_list.append(3)
                if self.partner_shipping_id.delivery_day_fri:
                    day_list.append(4)
                if self.partner_shipping_id.delivery_day_sat:
                    day_list.append(5)
                if self.partner_shipping_id.delivery_day_sun:
                    day_list.append(6)
            else:
                if self.partner_shipping_id.zip_delivery_id:
                    if self.partner_shipping_id.zip_delivery_day_mon:
                        day_list.append(0)
                    if self.partner_shipping_id.zip_delivery_day_tue:
                        day_list.append(1)
                    if self.partner_shipping_id.zip_delivery_day_wed:
                        day_list.append(2)
                    if self.partner_shipping_id.zip_delivery_day_thu:
                        day_list.append(3)
                    if self.partner_shipping_id.zip_delivery_day_fri:
                        day_list.append(4)
                    if self.partner_shipping_id.zip_delivery_day_sat:
                        day_list.append(5)
                    if self.partner_shipping_id.zip_delivery_day_sun:
                        day_list.append(6)
            weekday = date.today().weekday()
            day_diff = 0
            if day_list:
                if any(weekday < i for i in day_list):
                    for i in day_list:
                        if weekday < i:
                            day_diff = i - weekday
                            break
                else:
                    day_diff = (6 - weekday) + day_list[0] + 1
                shipping_date = date.today() + relativedelta(days=day_diff)
            self.release_date = shipping_date
            self.deliver_by = shipping_date
            self.carrier_id = self.partner_shipping_id.property_delivery_carrier_id
        else:
            self.carrier_id = self.partner_id and self.partner_id.property_delivery_carrier_id or False

    @api.onchange('carrier_id', 'order_line')
    def onchange_delivery_carrier_method(self):
        """ onchange delivery carrier,
            recompute the delicery price
        """
        if self.carrier_id:
            self.get_delivery_price()

    @api.model
    def create(self, vals):
        if vals.get('storage_contract'):
            sequence = self.env.ref('price_paper.seq_sc_sale_order', raise_if_not_found=False)
            if sequence:
                vals['name'] = sequence._next()
        return super(SaleOrder, self).create(vals)

    @api.multi
    def write(self, vals):
        """
        auto save the delivery line.
        """

        res = super(SaleOrder, self).write(vals)
        if not self._context.get('from_import'):
            self.check_payment_term()
            for order in self:
                if 'state' not in vals or 'state' in vals and vals['state'] != 'done':
                    if order.carrier_id:
                        order.adjust_delivery_line()
                    else:
                        order._remove_delivery_line()
        return res

    @api.multi
    def copy(self, default=None):
        ctx = dict(self.env.context)
        self = self.with_context(ctx)
        new_so = super(SaleOrder, self).copy(default=default)
        for line in new_so.order_line:
            if line.is_delivery:
                line.product_uom_qty = 1
        return new_so

    @api.model
    @api.returns('self',
                 upgrade=lambda self, value, args, offset=0, limit=None, order=None,
                                count=False: value if count else self.browse(value),
                 downgrade=lambda self, value, args, offset=0, limit=None, order=None,
                                  count=False: value if count else value.ids)
    def search(self, args, offset=0, limit=None, order=None, count=False):
        records = super(SaleOrder, self).search(args, offset, limit, order, count)
        user = self.env.user
        if self._context.get('my_draft'):
            return records.filtered(lambda s: s.user_id == user or user.partner_id in s.sales_person_ids)
        elif self._context.get('my_orders'):
            return records.filtered(lambda s: s.user_id == user or user.partner_id in s.sales_person_ids)
        return records

    def get_delivery_price(self):
        """
        overriden to bypass the delivery price get block for confirmed orders
        """
        for order in self.filtered(lambda o: o.state in ('draft', 'sent', 'sale') and len(o.order_line) > 0):
            # or on an SO that has no lines yet
            order.delivery_rating_success = False
            res = order.carrier_id.rate_shipment(order)
            if res['success']:
                order.delivery_rating_success = True
                order.delivery_price = res['price']
                order.delivery_message = res['warning_message']
            else:
                order.delivery_rating_success = False
                order.delivery_price = 0.0
                order.delivery_message = res['error_message']

    @api.multi
    def adjust_delivery_line(self):
        """
        method written to adjust delivery charges line in order line
        upon form save with changes in delivery method in sale order record
        """
        for order in self:
            #            if not order.delivery_rating_success and order.order_line:
            #                raise UserError(_('Please use "Check price" in order to compute a shipping price for this quotation.'))

            price_unit = order.carrier_id.rate_shipment(order)['price']
            delivery_line = self.env['sale.order.line'].search(
                [('order_id', '=', order.id), ('is_delivery', '=', True)])
            if not delivery_line and order.order_line:
                # TODO check whether it is safe to use delivery_price here
                order._create_delivery_line(order.carrier_id, price_unit)

            if delivery_line:

                # Apply fiscal position to get taxes to be applied
                taxes = order.carrier_id.product_id.taxes_id.filtered(lambda t: t.company_id.id == order.company_id.id)
                taxes_ids = taxes.ids
                if order.partner_id and order.fiscal_position_id:
                    taxes_ids = order.fiscal_position_id.map_tax(taxes, order.carrier_id.product_id,
                                                                 order.partner_id).ids

                # reset delivery line
                delivery_line.product_id = order.carrier_id.product_id.id
                delivery_line.price_unit = price_unit
                delivery_line.name = order.carrier_id.name
                delivery_line.product_uom_qty = delivery_line.product_uom_qty if delivery_line.product_uom_qty > 1 else 1
                delivery_line.product_uom = order.carrier_id.product_id.uom_id.id

        return True

    @api.multi
    @api.onchange('partner_id')
    def onchange_partner_id(self):
        res = super(SaleOrder, self).onchange_partner_id()
        if self.partner_id:
            addr = self.partner_id.address_get(['delivery', 'invoice'])
            self.partner_invoice_id = self.partner_id.id
            self.invoice_address_id = addr['invoice']
            shipping_addr = self.partner_id.child_ids.filtered(
                lambda rec: rec.type == 'delivery' and rec.default_shipping == True)
            if shipping_addr:
                self.partner_shipping_id = shipping_addr.id
            else:
                self.partner_shipping_id = self.partner_id.id
        else:
            self.invoice_address_id = False
        return res

    @api.multi
    def _prepare_invoice(self):
        self.ensure_one()
        res = super(SaleOrder, self)._prepare_invoice()
        if res:
            res['invoice_address_id'] = self.invoice_address_id.id
        return res

    @api.depends('order_line.profit_margin')
    def calculate_gross_profit(self):
        """
        Compute the gross profit of the SO.
        """
        for order in self:
            gross_profit = 0
            for line in order.order_line:
                gross_profit += line.profit_margin
                # if line.is_delivery:
                #     if order.carrier_id:
                #         gross_profit += line.price_subtotal
                #         price_unit = order.carrier_id.average_company_cost

                #         gross_profit -= price_unit
                # else:
                #     gross_profit += line.profit_margin
            if order.partner_id.payment_method == 'credit_card':
                gross_profit -= order.amount_total * 0.03
            if order.payment_term_id.discount_per > 0:
                gross_profit -= order.amount_total * (order.payment_term_id.discount_per / 100)
            order.update({'gross_profit': round(gross_profit, 2)})

    @api.constrains('release_date', 'deliver_by')
    def get_release_date_warning(self):

        if not self.release_date:
            self.release_date = date.today() + timedelta(days=1)
        if not self.deliver_by:
            self.deliver_by = date.today() + timedelta(days=1)

        if self.release_date and self.release_date < date.today():
            raise ValidationError(_('Earliest Delivery Date should be greater than Current Date'))

    @api.onchange('release_date')
    def onchange_release_date_warning(self):
        if self.release_date and self.release_date > date.today() + timedelta(days=+6):
            msg = {'warning': {'title': _('Warning'), 'message': _('Earliest Delivery Date is greater than 1 week')}}
            return msg

    def compute_credit_warning(self):

        for order in self:
            debit_due = self.env['account.move.line'].search(
                [('partner_id', '=', order.partner_id.id), ('full_reconcile_id', '=', False),
                 ('amount_residual', '>', 0),
                 ('date_maturity', '<', date.today()), ('invoice_id', '!=', False)], order='date_maturity desc')
            msg = ''
            msg1 = ''
            if debit_due:
                for rec in debit_due.mapped('invoice_id'):
                    if rec.type == "out_invoice" and rec.state not in ('paid', 'cancel'):
                        term_line = rec.payment_term_id.line_ids.filtered(lambda r: r.value == 'balance')
                        date_due = rec.date_due
                        if term_line and term_line.grace_period:
                            date_due = rec.date_due + timedelta(days=term_line.grace_period)
                        if date_due and date_due < date.today() and rec.number:
                            msg = msg + '%s, ' % (rec.number)
                if msg:
                    msg = 'Customer has pending invoices.\n' + msg
            if order.partner_id.credit + order.amount_total > order.partner_id.credit_limit:
                msg += "\nCustomer Credit limit Exceeded.\n%s's Credit limit is %s and due amount is %s\n" % (
                    order.partner_id.name, order.partner_id.credit_limit,
                    (order.partner_id.credit + order.amount_total))

            for order_line in order.order_line.filtered(lambda r: not r.storage_contract_line_id):
                if order_line.price_unit < order_line.working_cost and not (
                        'rebate_contract_id' in order_line and order_line.rebate_contract_id):
                    msg1 = '[%s]%s ' % (order_line.product_id.default_code,
                                        order_line.product_id.name) + "Unit Price is less than  Product Cost Price"

            order.credit_warning = msg
            order.low_price_warning = msg1

    @api.multi
    def action_release_credit_hold(self):
        """
        release hold sale order for credit limit exceed.
        """
        for order in self:
            order.write({'is_creditexceed': False, 'ready_to_release': True})
            order.message_post(body="Credit Team Approved")
            if order.release_price_hold:
                order.hold_state = 'release'
                order.action_confirm()
            else:
                order.hold_state = 'price_hold'

    @api.multi
    def action_release_price_hold(self):
        """
        release hold sale order for low price.
        """
        for order in self:
            order.write({'is_low_price': False, 'release_price_hold': True})
            order.message_post(body="Sale Team Approved")
            if order.ready_to_release:
                order.hold_state = 'release'
                order.action_confirm()
            else:
                order.hold_state = 'credit_hold'

    def check_credit_limit(self):
        """
        wheather the partner's credit limit exceeded or
        partner has pending invoices block the sale order confirmation
        and display warning message.
        """
        for order in self:
            msg = order.credit_warning and order.credit_warning or ''
            if msg:
                team = self.env['helpdesk.team'].search([('is_credit_team', '=', True)], limit=1)
                if team:
                    vals = {'name': 'Sale order with Credit Limit exceeded partner or Partner has pending Invoice.',
                            'team_id': team and team.id,
                            'description': 'Order : ' + order.name + '\n' + msg,
                            }
                    # ticket = self.env['helpdesk.ticket'].create(vals)
                order.write({'is_creditexceed': True, 'ready_to_release': False})
                order.message_post(body=msg)
                return msg
            else:
                order.write({'is_creditexceed': False, 'ready_to_release': True})
                return ''

    def check_low_price(self):
        """
        wheather order contains low price line
        block the sale order confirmation
        and display warning message.
        """
        for order in self:
            msg1 = order.low_price_warning and order.low_price_warning or ''
            if msg1:
                team = self.env['helpdesk.team'].search([('is_sales_team', '=', True)], limit=1)
                if team:
                    vals = {'name': 'Sale order with Product below working cost',
                            'team_id': team and team.id,
                            'description': 'Order : ' + order.name + '\n' + msg1,
                            }
                    # ticket = self.env['helpdesk.ticket'].create(vals)
                order.write({'is_low_price': True, 'release_price_hold': False})
                order.message_post(body=msg1)
                return msg1
            else:
                order.write({'is_low_price': False, 'release_price_hold': True})
                return ''

    @api.onchange('payment_term_id')
    def onchange_payment_term(self):
        user = self.env.user
        for order in self:
            partner_payment_term = order.partner_id and order.partner_id.property_payment_term_id
            if (order.payment_term_id.id != partner_payment_term.id) and not user.has_group(
                    'account.group_account_manager'):
                order.payment_term_id = partner_payment_term.id
                return {'warning': {'title': _('Invalid Action!'),
                                    'message': "You dont have the rights to change the payment terms of this customer."}}

    @api.multi
    def check_payment_term(self):
        """
        Can only proceed with order if payment term is set
        """
        user = self.env.user
        for order in self:
            if not order.payment_term_id:
                raise ValidationError(_('Payment term is not set for this order please set to proceed.'))

    @api.multi
    def action_confirm(self):
        """
        create record in price history
        and also update the customer pricelist if needed.
        create invoice for bill_with_goods customers.
        """

        if self._context.get('from_import'):
            res = super(SaleOrder, self).action_confirm()
        else:
            if not self.carrier_id:
                raise ValidationError(_('Delivery method should be set before confirming an order'))
            warning = ''
            if not self.ready_to_release:
                warning += self.check_credit_limit()
                if warning:
                    self.hold_state = 'credit_hold'
            if not self.release_price_hold:
                warning1 = self.check_low_price()
                if warning1:
                    self.hold_state = 'both_hold'
                    if not warning:
                        self.hold_state = 'price_hold'
                    warning = warning + warning1
            if warning:
                context = {'warning_message': warning}
                view_id = self.env.ref('price_paper.view_sale_warning_wizard').id
                return {
                    'name': _('Sale Warning'),
                    'view_type': 'form',
                    'view_mode': 'form',
                    'res_model': 'sale.warning.wizard',
                    'view_id': view_id,
                    'type': 'ir.actions.act_window',
                    'context': context,
                    'target': 'new'
                }
            if self.hold_state in ('credit_hold', 'price_hold', 'both_hold'):
                self.hold_state = 'release'

            res = super(SaleOrder, self).action_confirm()

            for order in self:
                for order_line in order.order_line:
                    if order_line.is_delivery:
                        continue
                    if not order_line.update_pricelist:
                        continue
                    order_line.update_price_list()

        return res

    @api.multi
    def import_action_confirm(self):
        self = self.with_context({'from_import': True})
        return self.action_confirm()

    @api.multi
    def view_sc_child_orders(self):
        self.ensure_one()
        action = self.env.ref('sale.action_orders').read()[0]
        if action:
            ids = self.order_line.mapped('storage_contract_line_ids.order_id').ids
            action.update({
                'domain': [
                    ('id', 'in', ids),
                    ('state', 'not in', ('sent', 'cancel')),
                    ('storage_contract', '=', False)]
            })
            return action

    @api.multi
    def add_purchase_history_to_so_line(self):
        """
        Return 'add purchase history to so wizard'
        """
        view_id = self.env.ref('price_paper.view_purchase_history_add_so_wiz').id
        history_from = datetime.today() - relativedelta(months=self.env.user.company_id.sale_history_months)
        products = self.order_line.mapped('product_id').ids
        sales_history = self.env['sale.history'].search(
            [('partner_id', '=', self.partner_id.id),
             ('product_id', 'not in', products), ('product_id.sale_ok', '=', True)])
        # addons product filtering
        addons_products = sales_history.mapped('product_id').filtered(lambda rec: rec.need_sub_product).mapped(
            'product_addons_list')
        if addons_products:
            sales_history = sales_history.filtered(lambda rec: rec.product_id not in addons_products)

        search_products = sales_history.mapped('product_id').ids
        context = {
            'default_sale_history_ids': [(6, 0, sales_history.ids)],
            'products': search_products
        }

        return {
            'name': _('Add purchase history to SO'),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'add.purchase.history.so',
            'view_id': view_id,
            'type': 'ir.actions.act_window',
            'context': context,
            'target': 'new'
        }

    def action_storage_contract_confirm(self):
        self.write({'state': 'sale', 'confirmation_date': fields.Datetime.today()})
        return True

    def run_storage(self):
        for order in self:
            route = self.env.ref('purchase_stock.route_warehouse0_buy', raise_if_not_found=True)
            so_lines = order.order_line.filtered(lambda r: r.product_id.type != 'service' and not r.display_type and not r.is_downpayment)
            so_lines.write({'route_id': route.id})
            errors = []
            for line in so_lines:
                group_id = line.order_id.procurement_group_id
                if not group_id:
                    group_id = self.env['procurement.group'].create({
                        'name': line.order_id.name,
                        'move_type': line.order_id.picking_policy,
                        'sale_id': line.order_id.id,
                        'partner_id': line.order_id.partner_shipping_id.id,
                    })
                    line.order_id.procurement_group_id = group_id
                else:
                    updated_vals = {}
                    if group_id.partner_id != line.order_id.partner_shipping_id:
                        updated_vals.update({'partner_id': line.order_id.partner_shipping_id.id})
                    if group_id.move_type != line.order_id.picking_policy:
                        updated_vals.update({'move_type': line.order_id.picking_policy})
                    if updated_vals:
                        group_id.write(updated_vals)

                values = line._prepare_procurement_values(group_id=group_id)
                product_qty = line.product_uom_qty
                procurement_uom = line.product_uom
                try:
                    self.env['procurement.group'].with_context(storage_contract=True).run(
                        line.product_id,
                        product_qty,
                        procurement_uom,
                        line.order_id.warehouse_id.lot_stock_id,
                        line.name,
                        line.order_id.name, values)
                except UserError as error:
                    errors.append(error.name)
            if errors:
                raise UserError('\n'.join(errors))

            #service line update
            purchase_orders = order.order_line.mapped('purchase_line_ids.order_id').filtered(lambda p: p.state == 'draft')
            for sr_line in order.order_line.filtered(lambda r: r.product_id.type == 'service' and not r.display_type and not r.is_downpayment):
                for po in purchase_orders:
                    fpos = po.fiscal_position_id
                    taxes = fpos.map_tax(
                        sr_line.product_id.supplier_taxes_id) if fpos else sr_line.product_id.supplier_taxes_id
                    if taxes:
                        taxes = taxes.filtered(lambda t: t.company_id.id == self.company_id.id)
                    price_unit = self.env['account.tax'].sudo()._fix_tax_included_price_company(
                        sr_line.price_unit,
                        sr_line.product_id.supplier_taxes_id,
                        taxes,
                        self.company_id
                    )
                    if po.currency_id and po.partner_id.currency_id != po.currency_id:
                        price_unit = po.partner_id.currency_id.compute(price_unit, po.currency_id)
                    product_in_supplier_lang = sr_line.product_id.with_context({
                        'lang': po.partner_id.lang,
                        'partner_id': po.partner_id.id,
                    })
                    name = '[%s] %s' % (sr_line.product_id.default_code, product_in_supplier_lang.display_name)
                    if product_in_supplier_lang.description_purchase:
                        name += '\n' + product_in_supplier_lang.description_purchase
                    purchase_qty_uom = sr_line.product_uom._compute_quantity(sr_line.product_uom_qty, sr_line.product_id.uom_po_id)
                    self.env['purchase.order.line'].create({
                        'name': sr_line.name,
                        'product_qty': purchase_qty_uom,
                        'product_id': sr_line.product_id.id,
                        'product_uom': sr_line.product_id.uom_po_id.id,
                        'price_unit': price_unit,
                        'date_planned': po.date_planned,
                        'taxes_id': [(6, 0, taxes.ids)],
                        'order_id': po.id,
                        'sale_line_id': sr_line.id,
                    })
            order.message_post(body='PO Created by : %s' % self.env.user.name)


SaleOrder()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    profit_margin = fields.Monetary(compute='calculate_profit_margin', string="Profit")
    price_from = fields.Many2one('customer.product.price', string='Product Pricelist')
    last_sale = fields.Text(compute='compute_last_sale_detail', string='Last sale details', store=False)
    product_onhand = fields.Float(string='Product Qty Available', compute='compute_available_qty',
                                  digits=dp.get_precision('Product Unit of Measure'), store=False)
    new_product = fields.Boolean(string='New Product', copy=False)
    manual_price = fields.Boolean(string='Manual Price Change', copy=False)
    is_last = fields.Boolean(string='Is last Purchase', copy=False)
    shipping_id = fields.Many2one(related='order_id.partner_shipping_id', string='Shipping Address')
    note = fields.Text('Note')
    note_type = fields.Selection(string='Note Type',
                                 selection=[('permanant', 'Save note'), ('temporary', 'Temporary Note')],
                                 default='temporary')
    confirmation_date = fields.Datetime(related='order_id.confirmation_date', string='Confirmation Date')
    price_lock = fields.Boolean(related='price_from.price_lock', readonly=True)

    # comment the below 2 lines while running sale order line import scripts
    lst_price = fields.Float(string='Standard Price', digits=dp.get_precision('Product Price'), store=True,
                             compute='_compute_lst_cost_prices')
    working_cost = fields.Float(string='Working Cost', digits=dp.get_precision('Product Price'), store=True,
                                compute='_compute_lst_cost_prices')

    # Uncomment the below 2 lines while running sale order line import scripts
    # lst_price = fields.Float(string='Standard Price', digits=dp.get_precision('Product Price'))
    # working_cost = fields.Float(string='Working Cost', digits=dp.get_precision('Product Price'))
    gross_volume = fields.Float(string="Gross Volume", compute='_compute_gross_weight_volume')
    gross_weight = fields.Float(string="Gross Weight", compute='_compute_gross_weight_volume')
    is_addon = fields.Boolean(string='Is Addon')
    update_pricelist = fields.Boolean(string="Update Pricelist", default=True, copy=False)
    remaining_qty = fields.Float(string="Remaining Quantity", compute='_compute_remaining_qty')
    similar_product_price = fields.Html(string='Similar Product Prices')
    sale_uom_ids = fields.Many2many('uom.uom', compute='_compute_sale_uom_ids')
    storage_remaining_qty = fields.Float(string="Remaining qty", compute='_compute_storage_delivered_qty',
                                         search='_search_storage_remaining_qty')
    storage_contract_line_id = fields.Many2one('sale.order.line', string='Contract Line')
    storage_contract_line_ids = fields.One2many('sale.order.line', 'storage_contract_line_id')
    selling_min_qty = fields.Float(string="Minimum Qty")
    note_expiry_date = fields.Date('Note Valid Upto')

    @api.depends('state', 'product_uom_qty', 'qty_delivered', 'qty_to_invoice', 'qty_invoiced',
                 'order_id.storage_contract')
    def _compute_invoice_status(self):
        super(SaleOrderLine, self)._compute_invoice_status()
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for line in self:
            if line.order_id.storage_contract:
                if float_compare(line.qty_invoiced, line.product_uom_qty, precision_digits=precision) >= 0:
                    line.invoice_status = 'invoiced'
                elif float_compare(line.qty_delivered, line.product_uom_qty, precision_digits=precision) == 0:
                    line.invoice_status = 'to invoice'
                elif float_compare(line.qty_delivered, line.product_uom_qty, precision_digits=precision) == 1:
                    line.invoice_status = 'upselling'
                else:
                    line.invoice_status = 'no'

    @api.depends('qty_invoiced', 'qty_delivered', 'product_uom_qty', 'order_id.state')
    def _get_to_invoice_qty(self):
        super(SaleOrderLine, self)._get_to_invoice_qty()
        for line in self:
            if line.order_id.storage_contract and line.order_id.state in ['done', 'released']:
                if line.product_id.invoice_policy == 'order':
                    line.qty_to_invoice = (line.product_uom_qty if not line.is_downpayment else 0) - line.qty_invoiced
                else:
                    line.qty_to_invoice = (line.qty_delivered if not line.is_downpayment else 0) - line.qty_invoiced

    @api.multi
    @api.depends('qty_delivered_method', 'qty_delivered_manual', 'analytic_line_ids.so_line',
                 'analytic_line_ids.unit_amount', 'analytic_line_ids.product_uom_id')
    def _compute_qty_delivered(self):
        super(SaleOrderLine, self)._compute_qty_delivered()
        for line in self:
            if line.order_id.storage_contract:
                for po_line in line.purchase_line_ids:
                    if po_line.state in ('purchase', 'done'):
                        line.qty_delivered = sum(po_line.move_ids.mapped('quantity_done'))
            else:
                if line.qty_delivered_method == 'stock_move':
                    qty = 0.0                    
                    for move in line.move_ids.filtered(lambda r: r.state == 'done' or r.is_transit is True and not r.scrapped and line.product_id == r.product_id):
                        if move.location_dest_id.usage == "customer":                            
                            if not move.origin_returned_move_id or (move.origin_returned_move_id and move.to_refund):
                                qty += move.product_uom._compute_quantity(move.quantity_done or move.reserved_availability, line.product_uom)                                
                        elif move.location_dest_id.usage != "customer" and move.to_refund:
                            qty -= move.product_uom._compute_quantity(move.product_uom_qty, line.product_uom)                    
                    line.qty_delivered = qty

    # @api.onchange('storage_contract_line_id')
    # def onchange_storage_contract_line_id(self):
    #     if self.storage_contract_line_id:
    #         self.product_id = self.storage_contract_line_id.product_id
    #         self.product_uom_qty = self.storage_contract_line_id.storage_remaining_qty if self.storage_contract_line_id.storage_remaining_qty < self.storage_contract_line_id.selling_min_qty else self.storage_contract_line_id.selling_min_qty

    @api.depends('product_id')
    def compute_available_qty(self):
        for line in self:
            line.product_onhand = line.product_id.qty_available - line.product_id.outgoing_qty

    @api.depends('product_uom_qty', 'storage_contract_line_ids')
    def _compute_storage_delivered_qty(self):
        for line in self:
            sale_lines = line.storage_contract_line_ids.filtered(lambda r: r.order_id.state != 'draft')
            line.storage_remaining_qty = line.product_uom_qty - sum(sale_lines.mapped('product_uom_qty'))

    @api.multi
    def _search_storage_remaining_qty(self, operator, value):
        ids = []
        if operator == '>':
            lines = self.search(
                [('order_id.storage_contract', '=', True), ('state', '=', 'released'), ('is_downpayment', '=', False)])
            for sl in lines:
                if (sl.product_uom_qty - sum(sl.storage_contract_line_ids.mapped('product_uom_qty'))) > value:
                    ids.append(sl.id)
        return [('id', 'in', ids)]

    @api.depends('product_id.sale_uoms')
    def _compute_sale_uom_ids(self):
        for rec in self:
            if rec.product_id:
                rec.sale_uom_ids = rec.product_id.sale_uoms
            else:
                rec.sale_uom_ids = False

    # @api.multi
    # def _prepare_invoice_line(self, qty):
    #     self.ensure_one()
    #     res = super(SaleOrderLine, self)._prepare_invoice_line(qty)
    #     if self.order_id.storage_contract:
    #         res.update({
    #             'price_unit': 0
    #         })
    #     return res

    def product_id_check_availability(self):
        if not self.product_id or not self.product_uom_qty or not self.product_uom:
            self.product_packaging = False
            return {}
        if self.product_id.type == 'product':
            precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            product = self.product_id.with_context(
                warehouse=self.order_id.warehouse_id.id,
                lang=self.order_id.partner_id.lang or self.env.user.lang or 'en_US'
            )
            product_qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
            if float_compare(product.qty_available - product.outgoing_qty, product_qty,
                             precision_digits=precision) == -1:
                is_available = self._check_routing()
                if not is_available:
                    message = _('You plan to sell %s %s of %s but you only have %s %s available in %s warehouse.') % \
                              (self.product_uom_qty, self.product_uom.name, self.product_id.name,
                               product.qty_available - product.outgoing_qty, product.uom_id.name,
                               self.order_id.warehouse_id.name)
                    # We check if some products are available in other warehouses.
                    if float_compare(product.qty_available - product.outgoing_qty,
                                     self.product_id.qty_available - self.product_id.outgoing_qty,
                                     precision_digits=precision) == -1:
                        message += _('\nThere are %s %s available across all warehouses.\n\n') % \
                                   (self.product_id.qty_available - self.product_id.outgoing_qty, product.uom_id.name)
                        for warehouse in self.env['stock.warehouse'].search([]):
                            quantity = self.product_id.with_context(
                                warehouse=warehouse.id).qty_available - self.product_id.with_context(
                                warehouse=warehouse.id).outgoing_qty
                            if quantity > 0:
                                message += "%s: %s %s\n" % (warehouse.name, quantity, self.product_id.uom_id.name)
                    warning_mess = {
                        'title': _('Not enough inventory!'),
                        'message': message
                    }
                    return {'warning': warning_mess}
        return {}

    @api.onchange('product_uom_qty', 'product_uom', 'route_id')
    def _onchange_product_id_check_availability(self):
        res = self.product_id_check_availability()
        if self.product_id and self.product_uom_qty and self.product_uom:
            if self.product_id.type == 'product':
                precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
                product = self.product_id.with_context(
                    warehouse=self.order_id.warehouse_id.id,
                    lang=self.order_id.partner_id.lang or self.env.user.lang or 'en_US'
                )
                product_qty = self.product_uom._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
                if float_compare(product.virtual_available, product_qty, precision_digits=precision) == -1:
                    is_available = self._check_routing()
                    if not is_available:
                        products = product.same_product_ids + product.same_product_rel_ids
                        if not products:
                            self.similar_product_price = False
                            return res
                        similar_product_price = "<table style='width:400px'>\
                                                <tr><th>Alternative Products</th><th>Price</th><th>UOM</th></tr>"
                        product_unit_price = self.price_unit / (product.count_in_uom * self.product_uom.factor_inv)
                        for item in products:
                            if item.count_in_uom > 0:
                                name = item.name
                                if item.default_code:
                                    name = '[' + item.default_code + ']' + name
                                price = product_unit_price * item.uom_id.factor_inv * item.count_in_uom
                                uom = item.uom_id.name

                                prices_all = self.env['customer.product.price']
                                for rec in self.order_id.partner_id.customer_pricelist_ids:
                                    if not rec.pricelist_id.expiry_date or rec.pricelist_id.expiry_date >= str(
                                            date.today()):
                                        prices_all |= rec.pricelist_id.customer_product_price_ids

                                prices_all = prices_all.filtered(lambda r: r.product_id.id == item.id)
                                product_price_rec = self.env['customer.product.price']
                                msg = ''
                                for price_rec in prices_all:
                                    if price_rec.pricelist_id.type == 'customer' and not price_rec.partner_id and prices_all.filtered(
                                            lambda r: r.partner_id):
                                        continue

                                    product_price_rec = price_rec
                                    break
                                if product_price_rec:
                                    price = price_rec.price
                                    uom = price_rec.product_uom.name

                                similar_product_price += "<tr><td>{}</td><td>{:.02f}</td><td>{}</td></tr>".format(name,
                                                                                                                  price,
                                                                                                                  uom)
                        similar_product_price += "</table>"
                        self.similar_product_price = similar_product_price
        return res

    @api.depends('product_uom_qty', 'qty_delivered')
    def _compute_remaining_qty(self):
        for line in self:
            line.remaining_qty = line.product_uom_qty - line.qty_delivered

    @api.depends('product_id.volume', 'product_id.weight')
    def _compute_gross_weight_volume(self):
        for line in self:
            volume = line.product_id.volume * line.product_qty
            weight = line.product_id.weight * line.product_qty
            line.gross_volume = volume
            line.gross_weight = weight

    @api.depends('product_id', 'product_uom')
    def _compute_lst_cost_prices(self):
        for line in self:
            if line.product_id and line.product_uom:
                uom_price = line.product_id.uom_standard_prices.filtered(lambda r: r.uom_id == line.product_uom)
                if uom_price:
                    line.lst_price = uom_price[0].price
                    if line.product_id.cost:
                        line.working_cost = uom_price[0].cost
                else:
                    line.product_id.job_queue_standard_price_update()
                    uom_price = line.product_id.uom_standard_prices.filtered(lambda r: r.uom_id == line.product_uom)
                    if uom_price:
                        line.lst_price = uom_price[0].price
                        if line.product_id.cost:
                            line.working_cost = uom_price[0].cost

    # @api.multi
    # def _prepare_invoice_line(self, qty):
    #     res = super(SaleOrderLine, self)._prepare_invoice_line(qty)
    #     if self.is_downpayment and self.product_id.is_storage_contract:
    #         account = self.product_id.storage_contract_account_id or self.product_id.property_account_income_id or self.product_id.categ_id.property_account_income_categ_id
    #
    #         if not account and self.product_id:
    #             raise UserError(_('Please define storage contract account for this product: "%s" (id:%d)".') %
    #                             (self.product_id.name, self.product_id.id))
    #
    #         fpos = self.order_id.fiscal_position_id or self.order_id.partner_id.property_account_position_id
    #         if fpos and account:
    #             account = fpos.map_account(account)
    #         res.update({'account_id': account.id, 'product_id': False})
    #     return res

    @api.multi
    def unlink(self):
        """
        lets users to bypass super unlink block for confirmed lines
        if line is delivery line
        """
        if self.exists():
            base = None
            unlinked_lines = self.env['sale.order.line']
            cascade_line = self.env['sale.order.line']
            for parentClass in self.__class__.__bases__:
                if parentClass._name == 'base':
                    base = parentClass

            for line in self:
                if line.is_delivery and base:
                    base.unlink(line)
                    unlinked_lines |= line
                elif line.exists() and line.product_id.need_sub_product:
                    cascade_line |= line + line.order_id.order_line.filtered(lambda rec: rec.is_addon)
                elif line.exists():
                    master_product = line.order_id.order_line.mapped('product_id').filtered(
                        lambda rec: rec.need_sub_product and line.product_id in rec.product_addons_list)
                    addon_products = master_product.product_addons_list
                    if master_product:
                        raise UserError(_(
                            "Product {} must be sold with \n\n {} \n\ncan't be removed without removing {}. \n\n Please refresh the page...!").format(
                            master_product.name, '\n'.join(['➥ ' + product.name for product in addon_products]),
                            master_product.name))

            return super(SaleOrderLine, (self - unlinked_lines) + cascade_line).unlink()

    @api.multi
    def name_get(self):

        result = []
        for line in self:
            result.append((line.id, "%s - %s - %s - %s" % (
            line.order_id.name, line.name, line.product_uom.name, line.order_id.date_order)))
        return result

    def update_price_list(self):
        """
        Update pricelist
        """
        if not self.is_delivery and not self.is_downpayment:
            unit_price = self.price_unit
            if self.product_id.uom_id == self.product_uom and self.product_uom_qty % 1 != 0.0:
                numer = self.price_unit * self.product_uom_qty
                denom = (int(self.product_uom_qty / 1.0) + (
                        (self.product_uom_qty % 1) * (100 + self.product_id.categ_id.repacking_upcharge) / 100))
                unit_price = numer / denom
            unit_price = float_round(unit_price, precision_digits=2)

            partner = self.order_id.partner_id.id
            if not self.order_id.storage_contract:

                partner_history = self.env['sale.order.line'].search(
                    [('product_id', '=', self.product_id.id), ('shipping_id', '=', self.shipping_id.id),
                     ('is_last', '=', True), ('product_uom', '=', self.product_uom.id)])
                partner_history and partner_history.write({'is_last': False})
                self.write({'is_last': True})

                sale_history = self.env['sale.history'].search(
                    [('partner_id', '=', partner), ('product_id', '=', self.product_id.id),
                     ('uom_id', '=', self.product_uom.id), '|', ('active', '=', True), ('active', '=', False)], limit=1)
                if sale_history:
                    sale_history.order_line_id = self
                else:
                    vals = {'order_line_id': self.id, 'partner_id': partner}
                    self.env['sale.history'].create(vals)

                sale_tax_history = self.env['sale.tax.history'].search(
                    [('partner_id', '=', self.order_id.partner_shipping_id.id),
                     ('product_id', '=', self.product_id.id)],
                    limit=1)
                is_tax = False
                if self.tax_id:
                    is_tax = True
                if sale_tax_history:
                    sale_tax_history.tax = is_tax
                else:
                    vals = {'product_id': self.product_id.id,
                            'partner_id': self.order_id.partner_shipping_id.id,
                            'tax': is_tax
                            }
                    self.env['sale.tax.history'].create(vals)

            # Create record in customer.product.price if not exist
            # if exist then check the price and update
            # if shared price exists then do not proceed with record creation

            if self.price_from and self.price_from.pricelist_id.type != 'competitor':
                if self.price_from.price != unit_price:
                    self.price_from.with_context({'from_sale': True}).price = unit_price
                    self.manual_price = True
            else:
                prices_all = self.env['customer.product.price']
                for rec in self.order_id.partner_id.customer_pricelist_ids:
                    if rec.pricelist_id.type in ('shared', 'customer') and (
                            not rec.pricelist_id.expiry_date or rec.pricelist_id.expiry_date >= date.today()):
                        prices_all |= rec.pricelist_id.customer_product_price_ids
                prices_all = prices_all.filtered(
                    lambda r: r.product_id.id == self.product_id.id and r.product_uom.id == self.product_uom.id and (
                            not r.partner_id or r.partner_id.id == self.order_id.partner_shipping_id.id))
                price_from = False
                for price_rec in prices_all:

                    if not price_rec.partner_id and prices_all.filtered(lambda r: r.partner_id):
                        continue

                    product_price = price_rec.price
                    price_from = price_rec
                    break
                if price_from:
                    if price_from.price < unit_price:
                        price_from.with_context({'from_sale': True}).price = unit_price
                        self.manual_price = True

                else:
                    price_lists = self.order_id.partner_id.customer_pricelist_ids.filtered(
                        lambda r: r.pricelist_id.type == 'customer').sorted(key=lambda r: r.sequence)

                    if not price_lists:
                        product_pricelist = self.env['product.pricelist'].create({
                            'name': self.order_id.partner_id.customer_code,
                            'type': 'customer',
                        })
                        price_lists = self.env['customer.pricelist'].create({
                            'pricelist_id': product_pricelist.id,
                            'partner_id': self.order_id.partner_id.id,
                            'sequence': 0
                        })
                    else:
                        price_from = price_lists[0].pricelist_id.customer_product_price_ids.filtered(
                            lambda r: r.product_id.id == self.product_id.id and r.product_uom.id == self.product_uom.id)
                        if price_from:
                            if price_from.price < unit_price:
                                price_from.with_context({'from_sale': True}).price = unit_price
                                self.manual_price = True
                    if not price_from:
                        price_from = self.env['customer.product.price'].with_context({'from_sale': True}).create({
                            'partner_id': self.order_id.partner_shipping_id.id,
                            'product_id': self.product_id.id,
                            'product_uom': self.product_uom.id,
                            'pricelist_id': price_lists[0].pricelist_id.id,
                            'price': unit_price
                        })
                    self.new_product = True
                if price_from:
                    self.price_from = price_from.id

    @api.multi
    def write(self, vals):
        res = super(SaleOrderLine, self).write(vals)
        for line in self:
            if vals.get('price_unit') and line.order_id.state == 'sale':
                line.update_price_list()
        return res

    @api.multi
    def _action_launch_stock_rule(self):
        """
        Launch procurement group run method with required/custom fields genrated by a
        sale order line. procurement group will launch '_run_pull', '_run_buy' or '_run_manufacture'
        depending on the sale order line product rule.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        errors = []
        for line in self:
            if line.state != 'sale' or not line.product_id.type in ('consu', 'product'):
                continue
            qty = line._get_qty_procurement()
            if float_compare(qty, line.product_uom_qty, precision_digits=precision) >= 0:
                continue

            group_id = line.order_id.procurement_group_id
            if not group_id:
                group_id = self.env['procurement.group'].create({
                    'name': line.order_id.name, 'move_type': line.order_id.picking_policy,
                    'sale_id': line.order_id.id,
                    'partner_id': line.order_id.partner_shipping_id.id,
                })
                line.order_id.procurement_group_id = group_id
            else:
                # In case the procurement group is already created and the order was
                # cancelled, we need to update certain values of the group.
                updated_vals = {}
                if group_id.partner_id != line.order_id.partner_shipping_id:
                    updated_vals.update({'partner_id': line.order_id.partner_shipping_id.id})
                if group_id.move_type != line.order_id.picking_policy:
                    updated_vals.update({'move_type': line.order_id.picking_policy})
                if updated_vals:
                    group_id.write(updated_vals)

            values = line._prepare_procurement_values(group_id=group_id)
            product_qty = line.product_uom_qty - qty

            procurement_uom = line.product_uom

            try:
                self.env['procurement.group'].run(
                    line.product_id, product_qty,
                    procurement_uom,
                    line.order_id.partner_shipping_id.property_stock_customer,
                    line.name,
                    line.order_id.name,
                    values)
            except UserError as error:
                errors.append(error.name)
        if errors:
            raise UserError('\n'.join(errors))
        orders = list(set(x.order_id for x in self))
        for order in orders:
            reassign = order.picking_ids.filtered(
                lambda x: x.state == 'confirmed' or (x.state in ['waiting', 'assigned'] and not x.printed))
            if reassign:
                reassign.action_assign()
        return True

    @api.model
    def create(self, vals):

        res = super(SaleOrderLine, self).create(vals)
        for line in res.filtered(lambda l: l.state == 'sale'):
            msg = _("Extra line with %s ") % (line.product_id.display_name,)
            line.move_ids.mapped('picking_id').message_post(body=msg)
        if res.product_id.need_sub_product and res.product_id.product_addons_list:
            for p in res.product_id.product_addons_list.filtered(
                    lambda rec: rec.id not in [res.order_id.order_line.mapped('product_id').ids]):
                s = self.create({
                    'product_id': p.id,
                    'product_uom': p.uom_id.id,
                    'product_uom_qty': res.product_uom_qty,
                    'order_id': res.order_id.id,
                    'is_addon': True
                })
                s.product_id_change()

        if res.order_id.state == 'sale':
            res.update_price_list()

        if res.note_type == 'permanant':
            note = self.env['product.notes'].search([
                ('product_id', '=', res.product_id.id),
                 ('partner_id', '=', res.order_id.partner_id.id),
                ('expiry_date', '>', date.today())
            ], limit=1)
            if not note:
                self.env['product.notes'].create({
                    'product_id': res.product_id.id,
                    'partner_id': res.order_id.partner_id.id,
                    'notes': res.note,
                    'expiry_date': res.note_expiry_date
                })
            else:
                note.notes = res.note
                note.expiry_date = res.note_expiry_date
        return res

    @api.depends('product_id', 'product_uom')
    def compute_last_sale_detail(self):
        """
        compute last sale detail of the product by the partner.
        """
        for line in self:
            if not line.order_id.partner_id:
                raise ValidationError(_('Please enter customer information first.'))
            line.last_sale = False
            if line.product_id and line.order_id.partner_shipping_id and line.product_uom:
                # last = self.env['sale.order.line'].sudo().search(
                #     [('order_id.partner_shipping_id', '=', line.order_id.partner_shipping_id.id),
                #      ('product_id', '=', line.product_id.id), ('product_uom', '=', line.product_uom.id),
                #      ('is_last', '=', True)], limit=1)

                last = self.env['sale.history'].sudo().search(
                    [('order_id.partner_id', '=', line.order_id.partner_id.id),
                     ('product_id', '=', line.product_id.id), ('uom_id', '=', line.product_uom.id),
                     ], limit=1)
                if last:
                    local = pytz.timezone(self.sudo().env.user.tz or "UTC")
                    last_date = datetime.strftime(pytz.utc.localize(
                        datetime.strptime(str(last.order_id.confirmation_date),
                                          DEFAULT_SERVER_DATETIME_FORMAT)).astimezone(local), "%m/%d/%Y %H:%M:%S")
                    line.last_sale = 'Order Date  - %s\nPrice Unit    - %s\nSale Order  - %s' % (
                        last_date, last.order_line_id.price_unit, last.order_id.name)
                else:
                    line.last_sale = 'No Previous information Found'
            else:
                line.last_sale = 'No Previous information Found'

    @api.depends('product_id', 'product_uom_qty', 'price_unit')
    def calculate_profit_margin(self):
        """
        Calculate profit margin for SO line
        """
        for line in self:
            if line.product_id:
                if line.is_delivery or line.is_downpayment or line.storage_contract_line_id:
                    line.profit_margin = 0.0
                    if line.is_delivery and line.order_id.carrier_id:
                        price_unit = line.order_id.carrier_id.average_company_cost
                        line.profit_margin = line.price_subtotal - price_unit
                else:
                    product_price = line.working_cost or 0
                    line_price = line.price_unit
                    if line.product_id.uom_id == line.product_uom and line.product_uom_qty % 1 != 0.0:
                        numer = line.price_unit * line.product_uom_qty
                        denom = (int(line.product_uom_qty / 1.0) + ((line.product_uom_qty % 1) * (
                                100 + line.product_id.categ_id.repacking_upcharge) / 100))
                        line_price = numer / denom
                    line.profit_margin = float_round((line_price - product_price) * line.product_uom_qty,
                                                     precision_digits=2)

    @api.multi
    @api.onchange('product_id')
    def product_id_change(self):
        """
        Add taxes automatically to sales lines if partner has a
        resale number and no taxes charged based on previous
        purchase history.
        Display a message from which pricelist the unit price is taken .

        """
        # TODO: update tax computational logic

        res = super(SaleOrderLine, self).product_id_change()
        lst_price = 0
        working_cost = 0
        if not self.product_id:
            res.update({'value': {'lst_price': lst_price, 'working_cost': working_cost}})
        if self.product_id:
            warn_msg = not self.product_id.purchase_ok and "This item can no longer be purchased from vendors" or ""
            if not self.order_id.storage_contract and sum(
                    [1 for line in self.order_id.order_line if line.product_id.id == self.product_id.id]) > 1:
                warn_msg += "\n{} is already in SO.".format(self.product_id.name)

            if self.order_id:
                partner_history = self.env['sale.tax.history'].search(
                    [('partner_id', '=', self.order_id and self.order_id.partner_shipping_id.id or False),
                     ('product_id', '=', self.product_id and self.product_id.id)])

                # if self.order_id and self.order_id.partner_id.vat and partner_history and not partner_history.tax:
                #     self.tax_id = [(5, _, _)] # clear all tax values, no Taxes to be used
                if partner_history and not partner_history.tax:
                    self.tax_id = [(5, _, _)]

                # force domain the tax_id field with only available taxes based on applied fpos
                if not res.get('domain', False):
                    res.update({'domain': {}})
                pro_tax_ids = self.product_id.taxes_id
                if self.order_id.fiscal_position_id:
                    taxes_ids = self.order_id.partner_shipping_id.property_account_position_id.map_tax(pro_tax_ids,
                                                                                                       self.product_id,
                                                                                                       self.order_id.partner_shipping_id).ids
                    res.get('domain', {}).update({'tax_id': [('id', 'in', taxes_ids)]})

            msg, product_price, price_from = self.calculate_customer_price()
            warn_msg += msg and "\n\n{}".format(msg)

            if warn_msg:
                res.update({'warning': {'title': _('Warning!'), 'message': warn_msg}})

            res.update({'value': {'price_unit': product_price, 'price_from': price_from}})

            # for uom only show those applicable uoms
            domain = res.get('domain', {})
            product_uom_domain = domain.get('product_uom', [])
            product_uom_domain.append(('id', 'in', self.product_id.sale_uoms.ids))

            # get this customers last time sale description for this product and update it in the line
            note = self.env['product.notes'].search(
                [('product_id', '=', self.product_id.id),
                ('partner_id', '=', self.order_id.partner_id.id),
                ('expiry_date', '>', date.today())], limit=1)
            if note:
                self.note = note.notes
                self.note_expiry_date = note.expiry_date
            else:
                self.note = ''

        return res

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        """
        assign the price unit from customer_product_price
        based on the pricelist.
        If there is no pricelist assign the standard price of product.
        """

        old_unit_price = self.price_unit
        res = super(SaleOrderLine, self).product_uom_change()
        res = res and res or {}
        warning, product_price, price_from = self.calculate_customer_price()
        if self.product_id and self.storage_contract_line_id:
            contract_line = self.storage_contract_line_id
            remaining_qty = contract_line.storage_remaining_qty
            if remaining_qty <= contract_line.selling_min_qty:
                self.product_uom_qty = remaining_qty
                self.price_unit = 0
            elif self.product_uom_qty <= remaining_qty:
                if self.product_uom_qty < contract_line.selling_min_qty:
                    warning_mess = {
                        'title': _('Less than Minimum qty'),
                        'message': _('You are going to sell less than minimum qty in the contract.')
                    }
                    self.product_uom_qty = 0
                    res.update({'warning': warning_mess})
                else:
                    self.price_unit = 0
            elif self.product_uom_qty > remaining_qty:
                warning_mess = {
                    'title': _('More than Storage contract'),
                    'message': _(
                        'You are going to Sell more than in storage contract.Only %s is remaining in this contract.' % (
                            remaining_qty))
                }
                self.product_uom_qty = 0
                res.update({'warning': warning_mess})
        else:
            if self._context.get('quantity', False):
                self.price_unit = old_unit_price
            else:
                self.price_unit = product_price
            self.price_from = price_from
            res = res and res or {}
            if self.product_uom_qty % 1 != 0.0:
                warning_mess = {
                    'title': _('Fractional Qty Alert!'),
                    'message': _('You plan to sell Fractional Qty.')
                }
                res.update({'warning': warning_mess})
        return res

    @api.multi
    def calculate_customer_price(self):
        """
        Fetch unit price from the relevant pricelist of partner
        if product is not found in any pricelist,set
        product price as Standard price of product
        """
        prices_all = self.env['customer.product.price']
        for rec in self.order_id.partner_id.customer_pricelist_ids:
            if not rec.pricelist_id.expiry_date or rec.pricelist_id.expiry_date >= str(date.today()):
                prices_all |= rec.pricelist_id.customer_product_price_ids

        prices_all = prices_all.filtered(
            lambda r: r.product_id.id == self.product_id.id and r.product_uom.id == self.product_uom.id and (
                    not r.partner_id or r.partner_id.id == self.order_id.partner_shipping_id.id or r.partner_id.id == self.order_id.partner_id.id))
        product_price = 0.0
        price_from = False
        msg = ''
        for price_rec in prices_all:

            if price_rec.pricelist_id.type == 'customer' and not price_rec.partner_id and prices_all.filtered(
                    lambda r: r.partner_id):
                continue

            if price_rec.pricelist_id.type not in ('customer', 'shared'):
                msg = "Unit price of this product is fetched from the pricelist %s." % (price_rec.pricelist_id.name)
            product_price = price_rec.price
            price_from = price_rec.id
            break
        if not price_from:
            if self.product_id and self.product_uom:
                uom_price = self.product_id.uom_standard_prices.filtered(lambda r: r.uom_id == self.product_uom)
                if uom_price:
                    product_price = uom_price[0].price

            msg = "Unit Price for this product is not found in any pricelists, fetching the unit price as product standard price."

        if self.product_id.uom_id == self.product_uom and self.product_uom_qty % 1 != 0.0:
            product_price = ((int(self.product_uom_qty / 1) * product_price) + (
                    (self.product_uom_qty % 1) * product_price * (
                    (100 + self.product_id.categ_id.repacking_upcharge) / 100))) / self.product_uom_qty
        product_price = float_round(product_price, precision_digits=2)
        return msg, product_price, price_from


SaleOrderLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
