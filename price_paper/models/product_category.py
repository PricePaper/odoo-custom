# -*- coding: utf-8 -*-

from odoo import fields, models, api, _


class ProductCategory(models.Model):
    _inherit = 'product.category'

    is_storage_contract = fields.Boolean(string='Is storage contract')
    sc_stock_valuation_account_id = fields.Many2one(
        'account.account',
        string="SC Stock Valuation Account"
    )
    sc_stock_liability_account_id = fields.Many2one(
        'account.account',
        string="SC Stock Liability Account"
    )


ProductCategory()
