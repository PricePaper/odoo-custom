# -*- coding: utf-8 -*-

from odoo import fields, models, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    customer_contract_ids = fields.Many2many('customer.contract', 'customer_contract_res_partner_rel', 'res_partner_id', 'customer_contract_id', string='Customer Contract')

ResPartner()
