# -*- coding: utf-8 -*-

from odoo import models, _

class ProcurementGroup(models.Model):
    _inherit = 'procurement.group'

    def _get_orderpoint_domain(self, company_id=False):
        """add purchase_ok = true in domain"""
        domain = super(ProcurementGroup, self)._get_orderpoint_domain()
        if domain:
            domain += [('product_id.purchase_ok', '=', True)]
        return domain

ProcurementGroup()
