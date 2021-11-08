# -*- coding: utf-8 -*-

from odoo import fields, models


class DeviatedCostContract(models.Model):
    _name = 'deviated.cost.contract'
    _description = 'Deviated Cost Contract'

    name = fields.Char(string="Contract Name")
    expiration_date = fields.Datetime(string="Expiration Date")
    partner_product_ids = fields.One2many('res.category.product.cost', 'partner_category_id', string="Products")
    partner_ids = fields.Many2many('res.partner', string="Partners")


DeviatedCostContract()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
