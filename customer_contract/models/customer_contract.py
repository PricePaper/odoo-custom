# -*- coding: utf-8 -*-

from odoo import fields, models, api


class CustomerContract(models.Model):
    _name = 'customer.contract'
    _description = 'Customer Contract'

    name = fields.Char(default='Draft', readonly=True)
    partner_ids = fields.Many2many('res.partner')
    expiration_date = fields.Datetime(string="Expiration Date")
    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed'), ('expired', 'Expired')], default='draft')
    product_line_ids = fields.One2many('customer.contract.line', 'contract_id', string='Products')

    @api.multi
    def action_confirm(self):
        self.ensure_one()
        self.state = 'confirmed'

        if self.name == 'Draft':
            sequence_val = self.env['ir.sequence'].next_by_code('customer.contract') or '/'
            self.name = sequence_val

    @api.multi
    def action_expire(self):
        self.write({'state': 'expired'})

    @api.multi
    def action_reset(self):
        self.write({'state': 'draft'})


CustomerContract()


class CustomerContractLine(models.Model):
    _name = 'customer.contract.line'
    _description = 'Customer Contract Line'

    product_id = fields.Many2one('product.product')
    product_qty = fields.Float('Quantity')
    remaining_qty = fields.Float('Remaining Qty', compute='_compute_remaining_qty', store=True)
    price = fields.Float()
    contract_id = fields.Many2one('customer.contract')
    state = fields.Selection(related='contract_id.state', readonly=True, store=True)
    sale_line_ids = fields.One2many('sale.order.line', 'customer_contract_line_id')


    @api.multi
    @api.depends('sale_line_ids.product_uom_qty', 'product_qty')
    def _compute_remaining_qty(self):
        for line in self:
            line.remaining_qty = line.product_qty - sum(line.sale_line_ids.mapped('product_uom_qty'))

    @api.multi
    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "%s (%s)" % (record.contract_id.name, record.product_id.default_code)))
        return result


CustomerContractLine()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
