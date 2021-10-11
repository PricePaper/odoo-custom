# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class CostChangePercentage(models.TransientModel):
    _name = 'cost.change.percentage'
    _description = "Cost change percentage"

    percentage_change = fields.Float(string='Percetage change')

    @api.multi
    def add_cost_change_lines(self):
        """
        Creating cost change lines
        """

        self.ensure_one()
        active_id = self._context.get('active_id')
        cost_change_parent = self.env['cost.change.parent'].browse(active_id)
        product_ids = self.env['product.product']
        for rec in cost_change_parent:
            domain = []
            if rec.vendor_id:
                product_ids = self.env['product.supplierinfo'].search([('name', '=', rec.vendor_id.id), ('product_id', '!=', False)]).mapped('product_id')
                domain.append(('id', 'in', product_ids.ids))
            if rec.category_id:
                domain.append(('categ_id.id', 'child_of', rec.category_id.ids))
            products = self.env['product.product'].search(domain)
            if products:
                product_ids = products

        for product in product_ids:
            cost_change_line = {
                'product_id': product.id,
                'price_filter': 'percentage',
                'price_change': self.percentage_change,
                'cost_change_parent': cost_change_parent and cost_change_parent.id
            }
            self.env['cost.change'].create(cost_change_line)
        return True




CostChangePercentage()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
