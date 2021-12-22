
from odoo import api, fields, models, _


class StockRule(models.Model):
    _inherit = 'stock.rule'


    def _get_qty_available_for_mto_qty(self, product, product_location, product_uom):
        virtual_available = product_location.qty_available
        return product.uom_id._compute_quantity(virtual_available, product_uom)

StockRule()
