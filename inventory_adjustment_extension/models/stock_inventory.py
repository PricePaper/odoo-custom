# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class Inventory(models.Model):
    _name = 'stock.inventory'
    _inherit = ['stock.inventory', 'mail.activity.mixin']

    vendor_id = fields.Many2one('res.partner', string='Vendor')

    @api.model
    def _selection_filter(self):
        res = super(Inventory, self)._selection_filter()
        res.extend([('vendor', _('Based on Vendor'))])
        return res

    def _get_inventory_lines_values(self):

        locations = self.env['stock.location'].search([('id', 'child_of', [self.location_id.id])])
        domain = ' location_id in %s'
        args = (tuple(locations.ids),)

        vals = []
        Product = self.env['product.product']
        # Empty recordset of products available in stock_quants
        quant_products = self.env['product.product']
        # Empty recordset of products to filter
        products_to_filter = self.env['product.product']

        # case 0: Filter on company
        if self.company_id:
            domain += ' AND company_id = %s'
            args += (self.company_id.id,)
        # case 1: Filter on One owner only or One product for a specific owner
        if self.partner_id:
            domain += ' AND owner_id = %s'
            args += (self.partner_id.id,)
        # case 2: Filter on One Lot/Serial Number
        if self.lot_id:
            domain += ' AND lot_id = %s'
            args += (self.lot_id.id,)
        # case 3: Filter on One product
        if self.product_id:
            domain += ' AND product_id = %s'
            args += (self.product_id.id,)
            products_to_filter |= self.product_id
        # case 4: Filter on A Pack
        if self.package_id:
            domain += ' AND package_id = %s'
            args += (self.package_id.id,)
        # case 5: Filter on One product category + Exahausted Products
        if self.category_id:
            categ_products = Product.search([('categ_id', '=', self.category_id.id)])
            domain += ' AND product_id = ANY (%s)'
            args += (categ_products.ids,)
            products_to_filter |= categ_products
        # case 6: Filter on vendor
        if self.vendor_id:
            vendor_products = Product.search([('seller_ids', '!=', False)])
            vendor_products = vendor_products.filtered(lambda r: r.seller_ids[0].name.id == self.vendor_id.id)
            domain += ' AND product_id = ANY (%s)'
            args += (vendor_products.ids,)
            products_to_filter |= vendor_products

        self.env.cr.execute("""SELECT product_id, sum(quantity) as product_qty, location_id, lot_id as prod_lot_id, package_id, owner_id as partner_id
            FROM stock_quant
            WHERE %s
            GROUP BY product_id, location_id, lot_id, package_id, partner_id """ % domain, args)

        for product_data in self.env.cr.dictfetchall():
            # replace the None the dictionary by False, because falsy values are tested later on
            for void_field in [item[0] for item in product_data.items() if item[1] is None]:
                product_data[void_field] = False
            product_data['theoretical_qty'] = product_data['product_qty']

            product_rec = Product.browse(product_data['product_id'])

            product_qty = 0
            for move in product_rec.stock_move_ids.filtered(lambda rec: rec.is_transit and rec.state != 'cancel' and rec.location_id.id == product_data['location_id']):
                if move.product_uom.id != product_rec.uom_id.id:
                    product_qty += move.product_uom._compute_quantity(move.quantity_done, product_rec.uom_id,
                                                                      rounding_method='HALF-UP')
                else:
                    product_qty += move.quantity_done
            product_qty
            theoretical_qty = product_data['product_qty'] - product_qty
            product_data['theoretical_qty'] = theoretical_qty
            product_data['product_qty'] = theoretical_qty

            if product_data['product_id']:
                product_data['product_uom_id'] = Product.browse(product_data['product_id']).uom_id.id
                quant_products |= Product.browse(product_data['product_id'])
            vals.append(product_data)
        if self.exhausted:
            exhausted_vals = self._get_exhausted_inventory_line(products_to_filter, quant_products)
            vals.extend(exhausted_vals)
        if self.product_id:
            for line in vals:
                loc = self.product_id.property_stock_location
                line['location_id'] = loc.id
        return vals

    @api.onchange('filter')
    def _onchange_filter(self):
        res = super(Inventory, self)._onchange_filter()
        if self.filter != 'vendor':
            self.vendor_id = False
        return res


Inventory()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
