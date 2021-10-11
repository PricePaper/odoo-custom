# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    @api.multi
    def do_scrap(self):
        return super(StockScrap, self.with_context(is_scrap = True)).do_scrap()
