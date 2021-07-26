from odoo import fields, models, api, _


class StorageContractPopUpWindow(models.TransientModel):
    _name = 'sc.popup.window'
    _description = 'Storage Contract PopUp Window for adding Existing contract'

    partner_id = fields.Many2one('res.partner', string='Customer')
    contract_line_id = fields.Many2one('sale.order.line', string='Storage Contract')
    order_qty = fields.Float(string='Order Quantity')

    @api.onchange('contract_line_id')
    def _onchange_contract_line(self):
        self.order_qty = self.contract_line_id.storage_remaining_qty if self.contract_line_id.storage_remaining_qty < self.contract_line_id.selling_min_qty else self.contract_line_id.selling_min_qty

    @api.onchange('order_qty')
    def _onchange_order_qty(self):
        res = {}
        if self.order_qty < self.contract_line_id.selling_min_qty:
            warning_mess = {
                'title': _('Less than Minimum qty'),
                'message': _('You are going to sell less than minimum qty in the contract.')
            }
            self.order_qty = 0
            res.update({'warning': warning_mess})
        elif self.order_qty > self.contract_line_id.storage_remaining_qty:
            warning_mess = {
                'title': _('More than Storage contract'),
                'message': _(
                    'You are going to Sell more than in storage contract.Only %s is remaining in this contract.' % (
                        self.contract_line_id.storage_remaining_qty))
            }
            self.order_qty = 0
            res.update({'warning': warning_mess})
        return res

    def add_sc_line(self):
        sc_line = self.contract_line_id
        line = self.env['sale.order.line'].create({
            'product_id': sc_line.product_id.id,
            'storage_contract_line_id': sc_line.id,
            'product_uom_qty': self.order_qty,
            'order_id': self._context.get('active_id')
        })
        line.product_id_change()
        line.product_uom_change()


StorageContractPopUpWindow()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
