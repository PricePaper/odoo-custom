# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import UserError

class StockMove(models.Model):
    _inherit = 'stock.move'

    picking_partner_id = fields.Many2one('res.partner', related='picking_id.partner_id', string='Partner')
    is_storage_contract = fields.Boolean(compute='_compute_is_storage_contract', store=True)
    po_original_qty = fields.Float(related="sale_line_id.product_uom_qty", string='Original Quantity (PO)', readonly=True)

    @api.depends('sale_line_id.storage_contract_line_id', 'sale_line_id.order_id.storage_contract')
    def _compute_is_storage_contract(self):
        for line in self:
            if line.sale_line_id:
                line.is_storage_contract = True if line.sale_line_id.storage_contract_line_id else True if line.sale_line_id.order_id.storage_contract else False

    def _search_picking_for_assignation(self):
        """
        Overriden to create one DO per one SO.
        """
        self.ensure_one()
        picking = self.env['stock.picking'].search([
            ('group_id', '=', self.group_id.id),
            ('location_dest_id', '=', self.location_dest_id.id),
            ('picking_type_id', '=', self.picking_type_id.id),
            ('printed', '=', False),
            ('state', 'in', ['draft', 'confirmed', 'waiting', 'partially_available', 'assigned'])], limit=1)
        return picking

    @api.multi
    def _get_accounting_data_for_valuation(self):
        """ Over ride to Return the accounts for inventory adjustment. """
        self.ensure_one()
        res = super(StockMove, self)._get_accounting_data_for_valuation()

        if self.is_storage_contract:
            valuation_account = self.product_id.categ_id.sc_stock_valuation_account_id
            if not valuation_account:
                raise UserError(_('Cannot find a SC Stock Valuation Account in product category: %s' % self.product_id.categ_id.name))

            return (res[0], res[1], res[2], valuation_account.id)

        if self._context.get('from_inv_adj', False):
            acc_src = False
            acc_dest = False
            if self.product_id.categ_id.inv_adj_input_account_id:
                acc_src = self.product_id.categ_id.inv_adj_input_account_id.id
            if self.product_id.categ_id.inv_adj_output_account_id:
                acc_dest = self.product_id.categ_id.inv_adj_output_account_id.id
            if not acc_src:
                raise UserError(_('Cannot find a Invenotry Adjustment stock input account for the product %s. You must define one on the product category, before processing this operation.') % (self.product_id.display_name))
            if not acc_dest:
                raise UserError(_('Cannot find a Invenotry Adjustment stock output account for the product %s. You must define one on the product category, before processing this operation.') % (self.product_id.display_name))
            res = (res[0], acc_src, acc_dest, res[3])
        return res

StockMove()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    picking_partner_id = fields.Many2one('res.partner', related='move_id.picking_partner_id', string='Partner')
    product_onhand_qty = fields.Float(string='Product Onhand QTY')
    inventory_id = fields.Many2one('stock.inventory', related='move_id.inventory_id', string='Inventory')


StockMoveLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
