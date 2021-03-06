# -*- coding: utf-8 -*-

import time
from datetime import datetime, date
from datetime import timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import ValidationError, UserError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_compare
from odoo.tools import float_round


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    release_date = fields.Date(string="Earliest Delivery Date", copy=False,
                               default=lambda s: s.get_release_deliver_default_date())
    customer_code = fields.Char(string='Partner Code', related='partner_id.customer_code')
    deliver_by = fields.Date(string="Deliver By", copy=False, default=lambda s: s.get_release_deliver_default_date())
    is_creditexceed = fields.Boolean(string="Credit limit exceeded", default=False, copy=False)
    credit_warning = fields.Text(string='Warning Message', compute='compute_credit_warning', copy=False)
    ready_to_release = fields.Boolean(string="Ready to release", default=False, copy=False)
    gross_profit = fields.Monetary(compute='calculate_gross_profit', string='Predicted Profit')
    is_quotation = fields.Boolean(string="Create as Quotation", default=False, copy=False)
    profit_final = fields.Monetary(string='Profit')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Draft Order Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True, track_visibility='onchange', track_sequence=3,
        default='draft')
    storage_contract = fields.Boolean(string="Storage Product", default=False, copy=True)
    total_volume = fields.Float(string="Total Order Volume", compute='_compute_total_weight_volume')
    total_weight = fields.Float(string="Total Order Weight", compute='_compute_total_weight_volume')
    total_qty = fields.Float(string="Total Order Quantity", compute='_compute_total_weight_volume')

    @api.depends('order_line.product_id', 'order_line.product_uom_qty')
    def _compute_total_weight_volume(self):
        for order in self:
            volume = 0
            weight = 0
            qty = 0
            for line in order.order_line:
                volume += line.gross_volume
                weight += line.gross_weight
                qty += line.product_uom_qty

            order.total_volume = volume
            order.total_weight = weight
            order.total_qty = qty

    @api.onchange('order_line')
    def onchange_order_line(self):
        if self.order_line and any(line.product_id.is_storage_contract for line in self.order_line):
            self.storage_contract = True
        else:
            self.storage_contract = False

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
    def action_create_draft_invoice_xmlrpc(self):

        self.action_invoice_create()
        self.invoice_ids.write({'move_name': self.note})
        return self.invoice_ids.ids

    @api.multi
    def action_create_storage_downpayment(self):
        """
        Create invoice for storage contract product down payment
        """

        sale_line_obj = self.env['sale.order.line']
        for order in self:
            for line in order.order_line:
                analytic_tag_ids = [(4, analytic_tag.id, None) for analytic_tag in line.analytic_tag_ids]
            so_lines = self.env['sale.order.line']
            for line in order.order_line:
                taxes = line.product_id.taxes_id.filtered(
                    lambda r: not order.company_id or r.company_id == order.company_id)
                if order.fiscal_position_id and taxes:
                    tax_ids = order.fiscal_position_id.map_tax(taxes, line.product_id, order.partner_shipping_id).ids
                else:
                    tax_ids = taxes.ids
                if line.product_id.is_storage_contract and not line.is_downpayment:
                    context = {'lang': order.partner_id.lang}
                    so_lines |= sale_line_obj.create({
                        'name': _('Advance: %s') % (time.strftime('%m %Y'),),
                        'price_unit': line.price_subtotal + line.price_tax,
                        'product_uom_qty': 0.0,
                        'order_id': order.id,
                        'discount': 0.0,
                        'product_uom': line.product_id.uom_id.id,
                        'product_id': line.product_id.id,
                        'analytic_tag_ids': analytic_tag_ids,
                        'tax_id': [(6, 0, tax_ids)],
                        'is_downpayment': True,
                    })
                    del context
            self._create_storage_downpayment_invoice(order, so_lines)
        return True

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
            self.carrier_id = self.partner_shipping_id and self.partner_shipping_id.property_delivery_carrier_id or self.partner_id and self.partner_id.property_delivery_carrier_id
        else:
            self.partner_id and self.partner_id.property_delivery_carrier_id

    @api.onchange('carrier_id', 'order_line')
    def onchange_delivery_carrier_method(self):
        """ onchange delivery carrier,
            recompute the delicery price
        """
        if self.carrier_id:
            self.get_delivery_price()

    @api.multi
    def write(self, vals):
        """
        auto save the delivery line.
        """

        res = super(SaleOrder, self).write(vals)
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
            shipping_date = date.today() + relativedelta(days=1)
            day_list = []
            if self.partner_id.change_delivery_days:
                if self.partner_id.delivery_day_mon:
                    day_list.append(0)
                if self.partner_id.delivery_day_tue:
                    day_list.append(1)
                if self.partner_id.delivery_day_wed:
                    day_list.append(2)
                if self.partner_id.delivery_day_thu:
                    day_list.append(3)
                if self.partner_id.delivery_day_fri:
                    day_list.append(4)
                if self.partner_id.delivery_day_sat:
                    day_list.append(5)
                if self.partner_id.delivery_day_sun:
                    day_list.append(6)
            else:
                if self.partner_id.zip_delivery_id:
                    if self.partner_id.zip_delivery_day_mon:
                        day_list.append(0)
                    if self.partner_id.zip_delivery_day_tue:
                        day_list.append(1)
                    if self.partner_id.zip_delivery_day_wed:
                        day_list.append(2)
                    if self.partner_id.zip_delivery_day_thu:
                        day_list.append(3)
                    if self.partner_id.zip_delivery_day_fri:
                        day_list.append(4)
                    if self.partner_id.zip_delivery_day_sat:
                        day_list.append(5)
                    if self.partner_id.zip_delivery_day_sun:
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
        return res

    @api.depends('order_line.profit_margin')
    def calculate_gross_profit(self):
        """
        Compute the gross profit of the SO.
        """
        for order in self:
            gross_profit = 0
            for line in order.order_line:
                if line.is_delivery:
                    if order.carrier_id:
                        gross_profit += line.price_subtotal
                        price_unit = order.carrier_id.rate_shipment(order)['price']
                        gross_profit -= price_unit
                else:
                    gross_profit += line.profit_margin
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

        if self.release_date and self.release_date > date.today() + timedelta(days=+6):
            raise ValidationError(_('Earliest Delivery Date is greater than 1 week'))

        if self.release_date and self.release_date < date.today():
            raise ValidationError(_('Earliest Delivery Date should be greater than Current Date'))

    def compute_credit_warning(self):

        for order in self:
            debit_due = self.env['account.move.line'].search(
                [('partner_id', '=', order.partner_id.id), ('full_reconcile_id', '=', False), ('debit', '!=', False),
                 ('date_maturity_grace', '<', date.today())], order='date_maturity_grace desc')
            msg = ''
            if order.partner_id.credit + order.amount_total > order.partner_id.credit_limit:
                msg = "Customer Credit limit Exceeded.\n%s's Credit limit is %s and due amount is %s\n" % (
                    order.partner_id.name, order.partner_id.credit_limit,
                    (order.partner_id.credit + order.amount_total))
            if debit_due:
                msg = msg + 'Customer has pending invoices.'
                for rec in debit_due:
                    msg = msg + '\n%s' % (rec.invoice_id.number)
            for order_line in order.order_line:
                if order_line.profit_margin < 0.0 and not (
                        'rebate_contract_id' in order_line and order_line.rebate_contract_id):
                    msg = msg + '[%s]%s ' % (order_line.product_id.default_code,
                                             order_line.product_id.name) + "Unit Price is less than  Product Cost Price"

            self.credit_warning = msg

    @api.multi
    def action_ready_to_release(self):
        """
        release the bolcked sale order.
        """
        for order in self:
            order.ready_to_release = True

    def check_credit_limit(self):
        """
        wheather the partner's credit limit exceeded or
        partner has pending invoices block the sale order confirmation
        and display warning message.
        """
        for order in self:
            msg = order.credit_warning and order.credit_warning or ''
            message = ''
            if msg:
                for order_line in order.order_line:
                    if order_line.profit_margin < 0.0 and not (
                            'rebate_contract_id' in order_line and order_line.rebate_contract_id):
                        message = message + '[%s]%s ' % (order_line.product_id.default_code,
                                                         order_line.product_id.name) + "Unit Price is less than  Product Cost Price\n"
                if message:
                    team = self.env['helpdesk.team'].search([('is_sales_team', '=', True)], limit=1)
                    if team:
                        vals = {'name': 'Sale order with Product below working cost',
                                'team_id': team and team.id,
                                'description': 'Order : ' + order.name + '\n' + message,
                                }
                        ticket = self.env['helpdesk.ticket'].create(vals)
                order.write({'is_creditexceed': True, 'ready_to_release': False})
                order.message_post(body=msg)
            else:
                order.write({'is_creditexceed': False, 'ready_to_release': True})
            if msg:
                return msg
            else:
                return {}

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
            if not self.ready_to_release:
                warning = self.check_credit_limit()
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

            if any(line.product_id.is_storage_contract for line in self.order_line):
                if not any(line.is_downpayment for line in self.order_line):
                    raise ValidationError(
                        _('Advance payment for Storage contract products should be created before order confirmation.'))
                if not all(invoice.state == 'paid' for invoice in self.invoice_ids):
                    raise ValidationError(_('Advance payment invoice for Storage contract products is not paid.'))
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
        self = self.with_context(from_import=True)
        return self.action_confirm()

    @api.multi
    def add_purchase_history_to_so_line(self):
        """
        Return 'add purchase history to so wizard'
        """
        view_id = self.env.ref('price_paper.view_purchase_history_add_so_wiz').id
        history_from = datetime.today() - relativedelta(months=self.env.user.company_id.sale_history_months)
        products = self.order_line.mapped('product_id').ids
        sales_history = self.env['sale.history'].search(
            [('partner_id', '=', self.partner_id.id), ('order_id.confirmation_date', '>=', history_from),
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


SaleOrder()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    profit_margin = fields.Monetary(compute='calculate_profit_margin', string="Profit")
    price_from = fields.Many2one('customer.product.price', string='Product Pricelist')
    last_sale = fields.Text(compute='compute_last_sale_detail', string='Last sale details', store=False)
    product_onhand = fields.Float(string='Product Qty Available', related='product_id.virtual_available',
                                  digits=dp.get_precision('Product Unit of Measure'))
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

    @api.multi
    def _prepare_invoice_line(self, qty):
        res = super(SaleOrderLine, self)._prepare_invoice_line(qty)
        if self.is_downpayment and self.product_id.is_storage_contract:
            account = self.product_id.storage_contract_account_id or self.product_id.property_account_income_id or self.product_id.categ_id.property_account_income_categ_id

            if not account and self.product_id:
                raise UserError(_('Please define storage contract account for this product: "%s" (id:%d)".') %
                                (self.product_id.name, self.product_id.id))

            fpos = self.order_id.fiscal_position_id or self.order_id.partner_id.property_account_position_id
            if fpos and account:
                account = fpos.map_account(account)
            res.update({'account_id': account.id, 'product_id': False})
        return res

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
            result.append((line.id, "%s - %s - %s" % (line.name, line.product_uom.name, line.order_id.date_order)))
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

            partner_history = self.env['sale.order.line'].search(
                [('product_id', '=', self.product_id.id), ('shipping_id', '=', self.shipping_id.id),
                 ('is_last', '=', True), ('product_uom', '=', self.product_uom.id)])
            partner_history and partner_history.write({'is_last': False})
            self.write({'is_last': True})

            partner = self.order_id.partner_id.id
            sale_history = self.env['sale.history'].search(
                [('partner_id', '=', partner), ('product_id', '=', self.product_id.id),
                 ('uom_id', '=', self.product_uom.id), '|', ('active', '=', True), ('active', '=', False)], limit=1)
            if sale_history:
                sale_history.order_line_id = self
            else:
                vals = {'order_line_id': self.id, 'partner_id': partner}
                self.env['sale.history'].create(vals)

            sale_tax_history = self.env['sale.tax.history'].search(
                [('partner_id', '=', self.order_id.partner_shipping_id.id), ('product_id', '=', self.product_id.id)],
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
                if self.price_from.price < unit_price:
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
                self.env['procurement.group'].run(line.product_id, product_qty, procurement_uom,
                                                  line.order_id.partner_shipping_id.property_stock_customer, line.name,
                                                  line.order_id.name, values)
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
            note = self.env['product.notes'].search(
                [('product_id', '=', res.product_id.id), ('partner_id', '=', res.order_id.partner_id.id)], limit=1)
            if not note:
                self.env['product.notes'].create({'product_id': res.product_id.id,
                                                  'partner_id': res.order_id.partner_id.id,
                                                  'notes': res.note
                                                  })
            else:
                note.notes = res.note
        return res

    @api.depends('product_id')
    def compute_last_sale_detail(self):
        """
        compute last sale detail of the product by the partner.
        """
        for line in self:
            if not line.order_id.partner_id:
                raise ValidationError(_('Please enter customer information first.'))
            line.last_sale = False
            if line.product_id and line.order_id.partner_shipping_id:
                last = self.env['sale.order.line'].sudo().search(
                    [('order_id.partner_shipping_id', '=', line.order_id.partner_shipping_id.id),
                     ('product_id', '=', line.product_id.id), ('product_uom', '=', line.product_uom.id),
                     ('is_last', '=', True)], limit=1)
                if last:
                    local = pytz.timezone(self.sudo().env.user.tz or "UTC")
                    last_date = datetime.strftime(pytz.utc.localize(
                        datetime.strptime(str(last.order_id.confirmation_date),
                                          DEFAULT_SERVER_DATETIME_FORMAT)).astimezone(local), "%m/%d/%Y %H:%M:%S")
                    line.last_sale = 'Order Date  - %s\nPrice Unit    - %s\nSale Order  - %s' % (
                        last_date, last.price_unit, last.order_id.name)
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
                if line.is_delivery or line.is_downpayment:
                    line.profit_margin = 0.0
                    if line.is_delivery and line.order_id.carrier_id:
                        price_unit = line.order_id.carrier_id.rate_shipment(line.order_id)['price']
                        line.profit_margin = line.price_subtotal - price_unit
                else:
                    product_price = line.working_cost or 0
                    line_price = line.price_unit
                    if line.product_id.uom_id == line.product_uom and line.product_uom_qty % 1 != 0.0:
                        numer = line.price_unit * line.product_uom_qty
                        denom = (int(line.product_uom_qty / 1.0) + ((line.product_uom_qty % 1) * (
                                100 + line.product_id.categ_id.repacking_upcharge) / 100))
                        line_price = numer / denom
                    line.profit_margin = float_round((line_price - product_price) * line.product_uom_qty, precision_digits=2)

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
            if sum([1 for line in self.order_id.order_line if line.product_id.id == self.product_id.id]) > 1:
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

                sale_history = self.env['sale.history'].search(
                    [('partner_id', '=', self.order_id and self.order_id.partner_id.id),
                     ('product_id', '=', self.product_id and self.product_id.id)])
                if sale_history:
                    if len(sale_history) > 1:
                        orders = sale_history.mapped('order_id')
                        last_date = max([rec.confirmation_date for rec in orders])
                        sale_history = sale_history.filtered(lambda r: r.order_date == last_date)
                    self.product_uom = sale_history.uom_id

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
                [('product_id', '=', self.product_id.id), ('partner_id', '=', self.order_id.partner_id.id)], limit=1)
            if note:
                self.note = note.notes
            else:
                self.note = self.name

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
        warning, product_price, price_from = self.calculate_customer_price()
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
                    not r.partner_id or r.partner_id.id == self.order_id.partner_shipping_id.id))
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
