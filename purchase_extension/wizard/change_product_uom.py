# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.tools import float_round

class ChangeProductUom(models.TransientModel):

    _name = 'change.product.uom'
    _description = 'Change Product UOM'


    product_id = fields.Many2one('product.product', string='Old Product')
    new_name = fields.Char('Name')
    new_default_code = fields.Char('Internal reference')
    new_uom = fields.Many2one('uom.uom', string='New UOM')
    new_sale_uoms = fields.Many2many('uom.uom', 'change_product_uom_rel', 'change_id', 'uom_id', string='New Sale UOMS')
    new_cost = fields.Float(string='Cost', digits=dp.get_precision('Product Price'))

    def create_duplicate_product(self):
        default_vals = {'name': self.new_name,
                        'default_code': self.new_default_code,
                        'standard_price': self.new_cost,
                        'uom_id': self.new_uom.id,
                        'uom_po_id': self.new_uom.id,
                        'sale_ok': False}
        res = self.product_id.with_context(from_change_uom=True).copy(default=default_vals)
        res.sale_uoms = [(5, _, _)]
        res.sale_uoms = self.new_sale_uoms
        lines = self.env['customer.product.price'].search([('product_id', '=', self.product_id.id)])
        default_1 = {'product_id': res.id}
        for line in lines:
            new_price = 0
            product = line.product_id
            old_working_cost = product.cost
            old_list_price = line.price
            if product.uom_id != line.product_uom:
                old_working_cost = product.uom_id._compute_price(product.cost, line.product_uom) * (
                            (100 + product.categ_id.repacking_upcharge) / 100)
            margin = float_round((old_list_price - old_working_cost) / old_list_price, precision_digits=2)
            new_working_cost = res.cost
            if res.uom_id != line.product_uom:
                new_working_cost = res.uom_id._compute_price(new_working_cost, line.product_uom) * (
                            (100 + res.categ_id.repacking_upcharge) / 100)
            new_price = float_round(new_working_cost / (1 - margin), precision_digits=2)
            default_1['price'] = new_price
            new_line = line.copy(default=default_1)
        return {
                'name': 'Product Variants',
                'type': 'ir.actions.act_window',
                'view_mode': 'form',
                'view_id': self.env.ref('product.product_normal_form_view').id,
                'res_model': 'product.product',
                'res_id': res.id,
            }

ChangeProductUom()
