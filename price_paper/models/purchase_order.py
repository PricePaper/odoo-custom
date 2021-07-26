# -*- coding: utf-8 -*-

from odoo import models, fields, registry, api, _
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError, AccessError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    storage_contract_po = fields.Boolean(compute='_compute_storage_contract_po', store=True, string='Storage Contract PO')

    @api.depends('order_line', 'order_line.sale_line_id')
    def _compute_storage_contract_po(self):
        for order in self:
            out = order.order_line.mapped('sale_line_id.order_id.storage_contract')
            if out and all(out):
                order.storage_contract_po = True
            else:
                order.storage_contract_po = False

    @api.multi
    def button_cancel(self):
        result = super(PurchaseOrder, self).button_cancel()
        self.mapped('order_line.sale_order_id').write({'sc_po_done': False})
        return result

    @api.multi
    def button_confirm(self):
        """
        cancel all other RFQ under the same purchase agreement
        """
        self.mapped('order_line.sale_order_id').action_done()
        return super(PurchaseOrder, self).button_confirm()


PurchaseOrder()


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
