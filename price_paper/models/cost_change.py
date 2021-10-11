# -*- coding: utf-8 -*-

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_round

class CostChangeParent(models.Model):
    _name = 'cost.change.parent'
    _description = 'Cost Change'

    # item_filter = fields.Selection([('product', 'Product'), ('vendor', 'Vendor and/or Product Category')],
                                   # string='Update Cost of', default='product')
    # price_filter = fields.Selection([('percentage', '%'), ('fixed', 'Fix to an Amount')], string='Increase Cost as',
                                    # default='fixed',
                                    # help='Percentage: increase cost by percentage \n Fix to an Amount: sets the price to the specified fixed amount')
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain=[('supplier', '=', True)])
    category_id = fields.Many2many('product.category', string="Product Category")
    is_done = fields.Boolean(string='Done', copy=False, default=False)
    run_date = fields.Date('Update Date', default=fields.Date.context_today, copy=False)
    update_customer_pricelist = fields.Boolean('Update Customer Pricelist', default=True)
    update_vendor_pricelist = fields.Boolean('Update Vendor Pricelist', default=True)
    update_standard_price = fields.Boolean('Update Standard Price', default=True)
    update_burden = fields.Boolean('Update Burden%')
    cost_change_lines = fields.One2many('cost.change', 'cost_change_parent', string='Lines')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    product_ids = fields.Many2many('product.product', string="Products", compute='_compute_product_ids')

    @api.depends('vendor_id', 'category_id')
    def _compute_product_ids(self):
        for rec in self:
            domain = []
            if rec.vendor_id:
                product_ids = self.env['product.supplierinfo'].search([('name', '=', rec.vendor_id.id), ('product_id', '!=', False)]).mapped('product_id')
                domain.append(('id', 'in', product_ids.ids))
            if rec.category_id:
                domain.append(('categ_id.id', 'child_of', rec.category_id.ids))
            products = self.env['product.product'].search(domain)
            if products:
                rec.product_ids = products.ids
            else:
                rec.product_ids = False

    @api.model
    def cost_change_cron(self):

        recs = self.env['cost.change.parent'].search([('is_done', '!=', 'True'), ('run_date', '<=', date.today())])
        for rec in recs:
            for line in rec.cost_change_lines:
                line.cost_change_method()
            rec.is_done = True
        return True

    @api.multi
    def add_percentage_lines(self):
        view_id = self.env.ref('price_paper.view_cost_change_percentage_wiz').id

        return {
            'name': _('Cost Change Cron'),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'cost.change.percentage',
            'view_id': view_id,
            'type': 'ir.actions.act_window',
            'target': 'new'
        }

    @api.multi
    def cost_change_method(self):
        for rec in self:
            for line in rec.cost_change_lines:
                line.cost_change_method()
            rec.is_done = True
    @api.multi
    @api.depends('run_date')
    def name_get(self):
        result = []
        for record in self:
            name = "%s" % (record.run_date)
            result.append((record.id, name))
        return result



CostChangeParent()


class CostChange(models.Model):
    _name = 'cost.change'
    _description = 'Cost Change Lines'

    item_filter = fields.Selection([('product', 'Product'), ('vendor', 'Vendor and/or Product Category')],
                                   string='Update Cost of', default='product')
    price_filter = fields.Selection([('percentage', '%'), ('fixed', 'Fix to an Amount')], string='Increase Cost as',
                                    default='fixed',
                                    help='Percentage: increase cost by percentage \n Fix to an Amount: sets the price to the specified fixed amount')
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain=[('supplier', '=', True)])
    category_id = fields.Many2many('product.category', string="Product Category")
    product_id = fields.Many2one('product.product', string="Product")
    price_change = fields.Float(string='Cost Change')
    is_done = fields.Boolean(string='Done', copy=False, default=False)
    run_date = fields.Date('Update Date', default=fields.Date.context_today, copy=False)
    update_customer_pricelist = fields.Boolean('Update Customer Pricelist', default=True)
    update_vendor_pricelist = fields.Boolean('Update Vendor Pricelist', default=True)
    update_standard_price = fields.Boolean('Update Standard Price', default=True)
    old_cost = fields.Float(compute='set_old_price', string='Old Cost', store=True)
    new_cost = fields.Float(compute='compute_new_cost', string='New Cost')
    price_difference = fields.Float(compute='compute_price_difference_percent', string="Price Difference")
    price_difference_per = fields.Float(compute='compute_price_difference_percent', string="Price Difference %")
    burden_change = fields.Float(string='Burden%')
    burden_old = fields.Float(string='Old Burden%')
    update_burden = fields.Boolean('Update Burden%')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    cost_change_parent = fields.Many2one('cost.change.parent', string='Cost change Record')

    @api.depends('new_cost', 'old_cost')
    def compute_price_difference_percent(self):
        for rec in self:
            if rec.product_id:
                rec.price_difference = rec.price_change and rec.new_cost - rec.old_cost
                rec.price_difference_per = rec.price_change and rec.old_cost and (
                            100 * (rec.new_cost - rec.old_cost)) / rec.old_cost or 0.00
            else:
                rec.price_difference = 0.00
                rec.price_difference_per = 0.00

    @api.depends('product_id')
    def set_old_price(self):
        for rec in self:
            if rec.product_id:
                rec.old_cost = rec.product_id.standard_price
                rec.burden_old = rec.product_id.burden_percent
                vendors = rec.product_id.seller_ids.mapped('name')
                vendors = vendors and vendors.ids

            else:
                rec.old_cost = 0.00

    @api.onchange('update_burden', 'product_id')
    def onchange_update_burden(self):
        for rec in self:
            if rec.update_burden and rec.product_id:
                rec.burden_change = rec.product_id.burden_percent
            else:
                rec.burden_change = 0.00

    @api.onchange('product_id', 'price_filter')
    def onchange_price_filter(self):
        for rec in self:
            if rec.price_filter == 'fixed' and rec.product_id:
                rec.price_change = rec.product_id.standard_price
            else:
                rec.price_change = 0.00

    @api.depends('old_cost', 'price_change', 'price_filter')
    def compute_new_cost(self):
        for rec in self:
            if rec.price_change:
                if rec.price_filter == 'fixed':
                    rec.new_cost = rec.price_change
                else:
                    rec.new_cost = rec.product_id and rec.product_id.standard_price * (
                                (100 + rec.price_change) / 100) or 0
            else:
                rec.new_cost == 0.00


    @api.multi
    def cost_change_method(self):


        for rec in self:
            # Update list price
            product = rec.product_id
            if rec.cost_change_parent.update_standard_price:
                rec.calculate_new_stdprice(product)
                standard_price_days = self.env.user.company_id.standard_price_config_days or 75
                product.standard_price_date_lock = date.today() + relativedelta(days=standard_price_days)

            # Update Customer pricelist
            if rec.cost_change_parent.update_customer_pricelist:
                customer_price_lists = self.env['customer.product.price'].search(
                    [('product_id', '=', product.id), ('pricelist_id.type', '!=', 'competitor')])
                today = date.today()
                for price_list_rec in customer_price_lists:
                    # skips the update pricelist if expiry lock is active and lock expiry date is set
                    if price_list_rec.price_lock and price_list_rec.lock_expiry_date > today:
                        continue

                    # skips the update pricelist if expiry lock is active and lock expiry date is set for the parent pricelist itself
                    if price_list_rec.pricelist_id and price_list_rec.pricelist_id.price_lock and price_list_rec.pricelist_id.lock_expiry_date > today:
                        continue

                    new_price = rec.calculate_new_price(price_list_rec)
                    new_price = float_round(new_price, precision_digits=2)
                    if price_list_rec.price != new_price:
                        price_list_rec.with_context({'user': self.user_id and self.user_id.id, 'cost_cron': True}).price = new_price

            # Update vendor price
            if rec.cost_change_parent.vendor_id:

                supplier_info = product.seller_ids.filtered(lambda r: r.name == rec.cost_change_parent.vendor_id)
                if rec.price_filter == 'fixed':
                    supplier_info.with_context({'user': self.user_id and self.user_id.id, 'cost_cron': True}).write({'price': rec.price_change})
                else:
                    supplier_info.with_context({'user': self.user_id and self.user_id.id, 'cost_cron': True}).price = float_round(supplier_info.price * ((100 + rec.price_change) / 100), precision_digits=2)

            # Update Fixed Cost
            if rec.price_filter == 'fixed':
                product.with_context({'user': self.user_id and self.user_id.id, 'cost_cron': True}).write(
                    {'standard_price': rec.price_change})
            else:
                product.with_context(
                    {'user': self.user_id and self.user_id.id, 'cost_cron': True}).standard_price = float_round(product.standard_price * (
                            (100 + rec.price_change) / 100), precision_digits=2)
            # Update burden%
            if rec.update_burden and rec.burden_change:
                product.with_context({'user': self.user_id and self.user_id.id, 'cost_cron': True}).write(
                    {'burden_percent': rec.burden_change})
            rec.is_done = True
        return True

    # @api.model
    # def cost_change_cron(self):
    #
    #     recs = self.env['cost.change'].search([('is_done', '!=', 'True'), ('run_date', '<=', date.today())])
    #     for rec in recs:
    #         rec.cost_change_method()
    #     return True

    def calculate_new_stdprice(self, product):
        for rec in product.uom_standard_prices:
            new_price = 0
            margin = rec.price_margin / 100
            if self.price_filter == 'fixed':
                new_working_cost = self.price_change * ((100 + product.burden_percent) / 100)
                if self.update_burden and self.burden_change:
                    new_working_cost = self.price_change * ((100 + self.burden_change) / 100)
                if product.uom_id != rec.uom_id:
                    new_price = (product.uom_id._compute_price(new_working_cost, rec.uom_id) * (
                                (100 + product.categ_id.repacking_upcharge) / 100)) / (1 - margin)
                else:
                    new_price = new_working_cost / (1 - margin)
            else:
                new_working_cost = (product.standard_price * (100 + self.price_change) / 100) * (
                            (100 + product.burden_percent) / 100)
                if self.update_burden and self.burden_change:
                    new_working_cost = (product.standard_price * (100 + self.price_change) / 100) * (
                                (100 + self.burden_change) / 100)
                if product.uom_id != rec.uom_id:
                    new_price = (product.uom_id._compute_price(new_working_cost, rec.uom_id) * (
                                (100 + product.categ_id.repacking_upcharge) / 100)) / (1 - margin)
                else:
                    new_price = new_working_cost / (1 - margin)
            new_price = float_round(new_price, precision_digits=2)
            if rec.price != new_price:
                rec.with_context({'user': self.user_id and self.user_id.id, 'cost_cron': True}).price = new_price

    def calculate_new_price(self, pricelist=None):

        if not pricelist:
            return 0
        new_price = 0
        product = pricelist.product_id
        old_working_cost = product.cost
        old_list_price = pricelist.price
        if product.uom_id != pricelist.product_uom:
            old_working_cost = product.uom_id._compute_price(product.cost, pricelist.product_uom) * (
                        (100 + product.categ_id.repacking_upcharge) / 100)

        if old_list_price:
            margin = (old_list_price - old_working_cost) / old_list_price

            if self.price_filter == 'fixed':
                new_working_cost = self.price_change * ((100 + product.burden_percent) / 100)
                if self.update_burden and self.burden_change:
                    new_working_cost = self.price_change * ((100 + self.burden_change) / 100)
                if product.uom_id != pricelist.product_uom:
                    new_price = (product.uom_id._compute_price(new_working_cost, pricelist.product_uom) * (
                                (100 + product.categ_id.repacking_upcharge) / 100)) / (1 - margin)
                else:
                    new_price = new_working_cost / (1 - margin)
            else:
                new_working_cost = (product.standard_price * (100 + self.price_change) / 100) * (
                            (100 + product.burden_percent) / 100)
                if self.update_burden and self.burden_change:
                    new_working_cost = (product.standard_price * (100 + self.price_change) / 100) * (
                                (100 + self.burden_change) / 100)
                if product.uom_id != pricelist.product_uom:
                    new_price = (product.uom_id._compute_price(new_working_cost, pricelist.product_uom) * (
                                (100 + product.categ_id.repacking_upcharge) / 100)) / (1 - margin)
                else:
                    new_price = new_working_cost / (1 - margin)
        return new_price

    @api.multi
    @api.depends('run_date')
    def name_get(self):
        result = []
        for record in self:
            name = "%s" % (record.run_date)
            result.append((record.id, name))
        return result

    @api.one
    @api.constrains('price_change')
    def check_if_zero_cost(self):
        if not self.price_change and self.product_id and self.product_id.type != 'service':
            raise ValidationError('Cost change field cannot be 0.00')
        if self.product_id and self.old_cost == 0:
            if self.update_standard_price or self.update_customer_pricelist:
                raise ValidationError('Please update only cost since old cost of the product is zero.(Uncheck standard price, customer pricelist update check boxes.)')



CostChange()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
