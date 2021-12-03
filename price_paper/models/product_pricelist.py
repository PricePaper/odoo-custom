# -*- coding: utf-8 -*-

from datetime import datetime, date

from dateutil.relativedelta import relativedelta

from odoo import fields, models, api


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    type = fields.Selection(string='Type',
                            selection=[('customer', 'Customer'), ('shared', 'Shared'), ('competitor', 'Competitor')])
    customer_pricelist_ids = fields.One2many('customer.pricelist', 'pricelist_id')
    customer_product_price_ids = fields.One2many('customer.product.price', 'pricelist_id')
    expiry_date = fields.Date('Valid Until')
    price_lock = fields.Boolean(string='Price Change Lock', default=False)
    lock_expiry_date = fields.Date(string='Lock Expiry date')
    partner_ids = fields.Many2many('res.partner', string='Customers', compute='_compute_partner', store=True)

    @api.onchange('price_lock')
    def onchange_price_lock(self):
        if self.price_lock:
            if self.env.user.company_id and self.env.user.company_id.price_lock_days:
                days = self.env.user.company_id.price_lock_days
                self.lock_expiry_date = date.today() + relativedelta(days=days)
        else:
            self.lock_expiry_date = False

    @api.depends('customer_pricelist_ids.partner_id')
    def _compute_partner(self):
        for pricelist in self:
            if pricelist.type != 'competitor':
                partner_ids = pricelist.customer_pricelist_ids.mapped('partner_id').ids
                if partner_ids:
                    pricelist.partner_ids = [(6, 0, partner_ids)]

    @api.model
    @api.returns('self',
                 upgrade=lambda self, value, args, offset=0, limit=None, order=None,
                                count=False: value if count else self.browse(value),
                 downgrade=lambda self, value, args, offset=0, limit=None, order=None,
                                  count=False: value if count else value.ids)
    def search(self, args, offset=0, limit=None, order=None, count=False):
        if self.env.user.has_group('price_paper.group_salesman_customer_own_pricelist') and not self.env.user.has_group(
                'base.group_system'):
            records = super(ProductPricelist, self).search(args, offset, limit, order, count)
            out_result = records.filtered(
                lambda rec: rec.type == 'competitor' or self.env.user.partner_id.id in rec.mapped(
                    'partner_ids').mapped('sales_person_ids').ids)
            return out_result
        return super(ProductPricelist, self).search(args, offset, limit, order, count)

    @api.model
    def _cron_update_price_change_lock(self):
        domain = [('price_lock', '=', True), ('lock_expiry_date', '<', datetime.today())]
        pricelists = self.search(domain)
        product_prices = self.env['customer.product.price'].search(domain)
        vals = {
            'price_lock': False,
            'lock_expiry_date': False
        }
        pricelists.write(vals)
        product_prices.write(vals)


ProductPricelist()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
