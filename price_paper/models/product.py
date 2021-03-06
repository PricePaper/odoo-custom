# -*- coding: utf-8 -*-

import operator as py_operator

from lxml import etree

from odoo import fields, models, api, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, ValidationError
from odoo.osv.orm import setup_modifiers

OPERATORS = {
    '<': py_operator.lt,
    '>': py_operator.gt,
    '<=': py_operator.le,
    '>=': py_operator.ge,
    '=': py_operator.eq,
    '!=': py_operator.ne
}


class ProductProduct(models.Model):
    _inherit = 'product.product'

    burden_percent = fields.Float(string='Burden %', default=lambda s: s.default_burden_percent())
    superseded = fields.One2many(comodel_name='product.superseded', inverse_name='product_child_id',
                                 string="Supersedes")
    cost = fields.Float(compute='compute_sale_burden', string="Working Cost", digits=dp.get_precision('Product Price'))
    sale_uoms = fields.Many2many('uom.uom', 'product_uom_rel', 'product_id', 'uom_id', string='Sale UOMS')
    vendor_id = fields.Many2one('res.partner', compute='compute_product_vendor', string="Vendor", store=True)
    uom_standard_prices = fields.One2many(comodel_name='product.standard.price', inverse_name='product_id',
                                          string="UOM STD Prices")

    is_bel_min_qty = fields.Boolean(string='Below Minimum Quantity', compute='compute_qty_status',
                                    search='_search_bel_min_qty')
    is_bel_crit_qty = fields.Boolean(string='Below Critical Quantity', compute='compute_qty_status',
                                     search='_search_bel_crit_qty')
    is_abv_max_qty = fields.Boolean(string='Above Max Quantity', compute='compute_qty_status',
                                    search='_search_abv_max_qty')
    is_storage_contract = fields.Boolean(string='Storage Contract Product')
    storage_contract_account_id = fields.Many2one('account.account', company_dependent=True,
                                                  string="Storage Contract Income Account",
                                                  domain=[('deprecated', '=', False)])
    standard_price_date_lock = fields.Date(string='Standard Price Lock Date')
    product_addons_list = fields.Many2many('product.product', 'product_addons_product_rel', 'product_id',
                                           'addon_product_id', string="Addons Product")
    need_sub_product = fields.Boolean(string='Need Sub-Products')
    similar_product_ids = fields.Many2many('product.product', 'product_similar_product_rel', 'product_id',
                                           'similar_product_id', string="Similar Product")

    @api.model
    def default_burden_percent(self):

        if self.env.user.company_id and self.env.user.company_id.burden_percent:
            return self.env.user.company_id.burden_percent
        return 0

    @api.model
    def fields_view_get(self, view_id=None, view_type=False, toolbar=False, submenu=False):
        res = super(ProductProduct, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar,
                                                          submenu=submenu)
        if not self.env.user.has_group('stock.group_stock_manager'):
            doc = etree.XML(res['arch'])
            if view_type == 'form':
                nodes = doc.xpath("//notebook//page[@name='superseded']//field[@name='superseded']")
                for node in nodes:
                    node.set('readonly', '1')
                    setup_modifiers(node, res['fields']['superseded'])
                    res['arch'] = etree.tostring(doc)
                return res
        return res

    @api.multi
    @api.depends('qty_available', 'orderpoint_ids.product_max_qty', 'orderpoint_ids.product_min_qty')
    def compute_qty_status(self):
        for product in self:
            if product.qty_available > product.reordering_max_qty:
                product.is_abv_max_qty = True
            else:
                product.is_abv_max_qty = False

            if product.qty_available < product.reordering_min_qty:
                product.is_bel_min_qty = True
            else:
                product.is_bel_min_qty = False

            if product.qty_available < (product.reordering_min_qty / 2):
                product.is_bel_crit_qty = True
            else:
                product.is_bel_crit_qty = False

    def _search_bel_min_qty(self, operator, value):
        return self._search_product_quantity_levels(operator, value, 'is_bel_min_qty')

    def _search_bel_crit_qty(self, operator, value):
        return self._search_product_quantity_levels(operator, value, 'is_bel_crit_qty')

    def _search_abv_max_qty(self, operator, value):
        return self._search_product_quantity_levels(operator, value, 'is_abv_max_qty')

    def _search_product_quantity_levels(self, operator, value, field):
        if field not in ('is_bel_min_qty', 'is_bel_crit_qty', 'is_abv_max_qty'):
            raise UserError(_('Invalid domain left operand %s') % field)
        if operator not in ('<', '>', '=', '!=', '<=', '>='):
            raise UserError(_('Invalid domain operator %s') % operator)
        if not isinstance(value, (float, int)):
            raise UserError(_('Invalid domain right operand %s') % value)

        ids = []
        for product in self.search([]):
            if OPERATORS[operator](product[field], value):
                ids.append(product.id)
        return [('id', 'in', ids)]

    @api.multi
    def toggle_active(self):
        """ remove superseded if there is a child product with superseded set while unarchiving,
        archive reordering rules before archiving product
        """

        result = super(ProductProduct, self).toggle_active()
        if self.qty_available > 0 and self.active:
            raise ValidationError(_("Can't archive product with inventory on hand"))

        supersede_obj = self.env['product.superseded']
        if self.active:
            to_unlink = supersede_obj.search([('old_product', '=', self.id)])
            to_unlink.unlink()
        return result

    @api.multi
    def write(self, vals):
        """
        overriden to update the customer product price when
        lst_price or burden_percent changes
        """
        # TODO Update price_list when standard price change
        for product in self:
            if 'standard_price' in vals:
                log_vals = {'change_date': fields.Datetime.now(),
                            'type': 'cost',
                            'old_price': self.standard_price,
                            'new_price': vals.get('standard_price'),
                            'user_id': self.env.user.id,
                            'uom_id': product.uom_id.id,
                            'price_from': 'manual',
                            'product_id': product.id
                            }
                if self._context.get('user', False):
                    log_vals['user_id'] = self._context.get('user', False)
                if self._context.get('cost_cron', False):
                    log_vals['price_from'] = 'cost_cron'
                self.env['product.price.log'].create(log_vals)
            if 'burden_percent' in vals:
                log_vals = {'change_date': fields.Datetime.now(),
                            'type': 'burden',
                            'old_price': self.burden_percent,
                            'new_price': vals.get('burden_percent'),
                            'user_id': self.env.user.id,
                            'uom_id': product.uom_id.id,
                            'price_from': 'manual',
                            'product_id': product.id
                            }
                if self._context.get('user', False):
                    log_vals['user_id'] = self._context.get('user', False)
                if self._context.get('cost_cron', False):
                    log_vals['price_from'] = 'cost_cron'
                self.env['product.price.log'].create(log_vals)
            if 'active' in vals and not vals.get('active'):
                if product.qty_available > 0:
                    raise ValidationError(_("Can't archive product with inventory on hand"))

                reordering_rules = self.env['stock.warehouse.orderpoint'].search(
                    [('product_id', 'in', self.ids), ('active', '=', True)])
                reordering_rules.toggle_active()

            if vals.get('burden_percent') or vals.get('standard_price'):
                # self.update_customer_product_price()
                for rec in product.uom_standard_prices:
                    if rec.cost > rec.price:
                        rec.price = rec.cost

        result = super(ProductProduct, self).write(vals)
        return result

    @api.model
    def create(self, vals):
        res = super(ProductProduct, self).create(vals)
        if 'standard_price' in vals:
            log_vals = {
                'change_date': fields.Datetime.now(),
                'type': 'cost',
                'new_price': vals.get('standard_price'),
                'user_id': self.env.user.id,
                'uom_id': res.uom_id.id,
                'product_id': res.id
            }
            if self._context.get('user', False):
                log_vals['user_id'] = self._context.get('user', False)
            self.env['product.price.log'].create(log_vals)
        if 'burden_percent' in vals:
            log_vals = {
                'change_date': fields.Datetime.now(),
                'type': 'burden',
                'new_price': vals.get('burden_percent'),
                'user_id': self.env.user.id,
                'uom_id': res.uom_id.id,
                'product_id': res.id
            }
            if self._context.get('user', False):
                log_vals['user_id'] = self._context.get('user', False)
            self.env['product.price.log'].create(log_vals)
        return res

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """
        overriden to display the superseded product when
        default code of archived product is entered.
        """
        if name:
            old_products = self.env['product.product'].search([('default_code', 'ilike', name), ('active', '=', False)])
            if old_products:
                new_products = self.env['product.product'].search([('superseded', 'in', old_products.ids)])
                if new_products:
                    return new_products.name_get()
        return super(ProductProduct, self).name_search(name=name, args=args, operator=operator, limit=limit)

    @api.depends('seller_ids')
    def compute_product_vendor(self):
        """
        Compute vendor of the product
         """
        for rec in self:
            rec.vendor_id = rec.seller_ids and rec.seller_ids[0].name.id or False

    @api.depends('standard_price', 'burden_percent')
    def compute_sale_burden(self):
        """
        Compute cost price by adding burden percentange
        """
        for rec in self:
            burden_factor = rec.burden_percent / 100
            burden = rec.standard_price * burden_factor
            if burden:
                rec.cost = burden + rec.standard_price
            else:
                rec.cost = rec.standard_price

    @api.onchange('sale_uoms')
    def onchange_sale_uoms(self):
        """
        """
        return {'domain': {'uom_id': ([('id', 'in', self.sale_uoms.ids)]),
                           'uom_po_id': ([('id', 'in', self.sale_uoms.ids)])}}


ProductProduct()


class ProductCategory(models.Model):
    _inherit = "product.category"

    repacking_upcharge = fields.Float(string="Repacking Charge %")
    categ_code = fields.Char(string='Category Code')
    standard_price = fields.Float(string="Class Standard Price Percent", digits=dp.get_precision('Product Price'))


ProductCategory()


class ProductUom(models.Model):
    _inherit = "uom.uom"

    product_ids = fields.Many2many('product.product', 'product_uom_rel', 'uom_id', 'product_id', string="Products")


ProductUom()


class ProductSuperseded(models.Model):
    _name = 'product.superseded'
    _description = 'Superseded Products'

    old_product = fields.Many2one('product.product', string="Old Product",
                                  domain=[('active', '=', False)], required=True, ondelete='cascade')
    product_child_id = fields.Many2one('product.product', string="New Product",
                                       readonly=True, required=True)

    @api.one
    @api.constrains('old_product', 'product_child_id')
    def check_duplicates(self):
        result = self.search([('old_product', '=', self.old_product.id),
                              ('product_child_id', '=', self.product_child_id.id),
                              ('id', '!=', self.id)])
        if result:
            raise UserError('Duplicate entry in superseded')


ProductSuperseded()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
