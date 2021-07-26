# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    over_processed = fields.Boolean(string='Over Processed', copy=False)

    @api.multi
    def action_sc_sync_with_receipt(self):
        self.ensure_one()
        for line in self.move_ids_without_package:
            if line.is_storage_contract:
                line.sale_line_id.order_id.action_unlock()
                line.purchase_line_id.product_qty = line.quantity_done
                line.sale_line_id.write({'product_uom_qty': line.quantity_done, 'qty_delivered': line.quantity_done})
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

StockRule()


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
