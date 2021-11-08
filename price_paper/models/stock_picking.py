# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    over_processed = fields.Boolean(string='Over Processed', compute='_compute_over_processed')

    @api.depends('move_ids_without_package.po_original_qty', 'move_ids_without_package.is_storage_contract')
    def _compute_over_processed(self):
        for record in self:
            if any([move.po_original_qty < move.quantity_done for move in record.move_ids_without_package if move.is_storage_contract and move.purchase_line_id]):
                record.over_processed = True
            else:
                record.over_processed = False

    @api.multi
    def action_sc_sync_with_receipt(self):
        self.ensure_one()
        for line in self.move_ids_without_package:
            done_flag = False
            if line.is_storage_contract:
                if line.sale_line_id.order_id.state == 'done':
                    done_flag = True
                    line.sale_line_id.order_id.action_unlock()
                line.purchase_line_id.product_qty = line.quantity_done
                line.sale_line_id.write({'product_uom_qty': line.quantity_done, 'qty_delivered': line.quantity_done})
                if done_flag:
                    line.sale_line_id.order_id.action_done()
        backorder_pick = self.env['stock.picking'].search([('backorder_id', '=', self.id), ('state', '!=', 'cancel')])
        if backorder_pick:
            backorder_pick.action_cancel()
            self.message_post(body=_("Back order <em>%s</em> <b>cancelled</b>.") % (",".join([b.name or '' for b in backorder_pick])))
        self.over_processed = False

    @api.multi
    def sync_over_processed(self):
        self.ensure_one()
        return {
            'name': 'Sync OverProcessed',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'stock.picking',
            'res_id': self.id,
            'view_id': self.env.ref('price_paper.view_stock_move_over_processed_window').id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    @api.multi
    def button_validate(self):
        self.ensure_one()
        result = super(StockPicking, self).button_validate()
        if self.picking_type_code == 'incoming':
            for line in self.move_lines:
                # print(line.is_storage_contract , line.purchase_line_id)
                # if input('dddddddd') == 'y':print(o)
                if line.is_storage_contract and line.purchase_line_id:
                    line.sale_line_id.qty_delivered = line.quantity_done
        return result

StockPicking()


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _make_po_get_domain(self, values, partner):
        domain = super(StockRule, self)._make_po_get_domain(values, partner)
        storage_contract = self._context.get('storage_contract')
        if storage_contract:
            domain += (
                ('storage_contract_po', '=', True),
            )
        return domain

    @api.multi
    def _run_buy(self, product_id, product_qty, product_uom, location_id, name, origin, values):
        procurement_group = values.get('group_id', False)
        order_point = values.get('orderpoint_id', False)
        if order_point or procurement_group and (procurement_group.sale_id and procurement_group.sale_id.storage_contract or not procurement_group.sale_id):
            return super(StockRule, self)._run_buy(product_id, product_qty, product_uom, location_id, name, origin, values)

        cache = {}
        suppliers = product_id.seller_ids\
            .filtered(lambda r: (not r.company_id or r.company_id == values['company_id']) and (not r.product_id or r.product_id == product_id) and r.name.active)
        if not suppliers:
            msg = _('There is no vendor associated to the product %s. Please define a vendor for this product.') % (product_id.display_name,)
            raise UserError(msg)
        supplier = self._make_po_select_supplier(values, suppliers)
        partner = supplier.name
        # we put `supplier_info` in values for extensibility purposes
        values['supplier'] = supplier
        domain = self._make_po_get_domain(values, partner)
        if domain in cache:
            po = cache[domain]

        else:
            po = self.env['purchase.order'].sudo().search([dom for dom in domain])
            po = po[0] if po else False
            cache[domain] = po

        if not po or po and origin not in po.origin.split(', '):
            vals = self._prepare_purchase_order(product_id, product_qty, product_uom, origin, values, partner)
            company_id = values.get('company_id') and values['company_id'].id or self.env.user.company_id.id
            po = self.env['purchase.order'].with_context(force_company=company_id).sudo().create(vals)

            cache[domain] = po
        elif not po.origin or origin not in po.origin.split(', '):
            if po.origin:
                if origin:
                    po.write({'origin': po.origin + ', ' + origin})
                else:
                    po.write({'origin': po.origin})
            else:
                po.write({'origin': origin})

        # Create Line
        po_line = False
        for line in po.order_line:
            if line.product_id == product_id and line.product_uom == product_id.uom_po_id:
                if line._merge_in_existing_line(product_id, product_qty, product_uom, location_id, name, origin, values):
                    vals = self._update_purchase_order_line(product_id, product_qty, product_uom, values, line, partner)
                    po_line = line.write(vals)
                    break
        if not po_line:
            vals = self._prepare_purchase_order_line(product_id, product_qty, product_uom, values, po, partner)
            self.env['purchase.order.line'].sudo().create(vals)


StockRule()


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
