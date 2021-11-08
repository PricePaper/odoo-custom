# -*- coding: utf-8 -*-

from odoo import api, fields, models, _

from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round



class StockQuant(models.Model):
    _inherit = 'stock.quant'

    quantity_onhand = fields.Float(compute='_compute_quantity_onhand_with_transit')


    @api.model
    def _update_reserved_quantity(self, product_id, location_id, quantity, lot_id=None, package_id=None, owner_id=None, strict=False):
        """ Increase the reserved quantity, i.e. increase `reserved_quantity` for the set of quants
        sharing the combination of `product_id, location_id` if `strict` is set to False or sharing
        the *exact same characteristics* otherwise. Typically, this method is called when reserving
        a move or updating a reserved move line. When reserving a chained move, the strict flag
        should be enabled (to reserve exactly what was brought). When the move is MTS,it could take
        anything from the stock, so we disable the flag. When editing a move line, we naturally
        enable the flag, to reflect the reservation according to the edition.

        ****Override to fix the broken UOM rounding issue****

        :return: a list of tuples (quant, quantity_reserved) showing on which quant the reservation
            was done and how much the system was able to reserve on it

        """
        self = self.sudo()
        rounding = product_id.uom_id.rounding
        quants = self._gather(product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=strict)
        reserved_quants = []

        if float_compare(quantity, 0, precision_rounding=rounding) > 0:
            # if we want to reserve
            available_quantity = self._get_available_quantity(product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id, strict=strict)

            if float_compare(quantity, available_quantity, precision_rounding=rounding) > 0:
                raise UserError(_('It is not possible to reserve more products of %s than you have in stock.') % product_id.display_name)
        elif float_compare(quantity, 0, precision_rounding=rounding) < 0:
            # if we want to unreserve
            rounding_digit = self.env['decimal.precision'].precision_get('Product Unit of Measure')
            available_quantity = sum(quants.mapped('reserved_quantity'))
            available_quantity = float_round(available_quantity, precision_digits=rounding_digit)
            if float_compare(abs(quantity), available_quantity, precision_rounding=rounding) > 0:
                if float_compare(abs(float_round(quantity, precision_digits=rounding_digit)), available_quantity, precision_rounding=rounding) > 0:
                    raise UserError(_('It is not possible to unreserve more products of %s than you have in stock.') % product_id.display_name)
        else:
            return reserved_quants

        for quant in quants:
            if float_compare(quantity, 0, precision_rounding=rounding) > 0:
                max_quantity_on_quant = quant.quantity - quant.reserved_quantity
                if float_compare(max_quantity_on_quant, 0, precision_rounding=rounding) <= 0:
                    continue
                max_quantity_on_quant = min(max_quantity_on_quant, quantity)
                quant.reserved_quantity += max_quantity_on_quant
                reserved_quants.append((quant, max_quantity_on_quant))
                quantity -= max_quantity_on_quant
                available_quantity -= max_quantity_on_quant
            else:
                max_quantity_on_quant = min(quant.reserved_quantity, abs(quantity))
                quant.reserved_quantity -= max_quantity_on_quant
                reserved_quants.append((quant, -max_quantity_on_quant))
                quantity += max_quantity_on_quant
                available_quantity += max_quantity_on_quant

            if float_is_zero(quantity, precision_rounding=rounding) or float_is_zero(available_quantity, precision_rounding=rounding):
                break
        return reserved_quants

    def _compute_quantity_onhand_with_transit(self):
        for rec in self:
            product_qty = 0
            for move in rec.product_id.stock_move_ids.filtered(lambda r: r.is_transit and r.location_id.id == rec.location_id.id and r.state != 'cancel'):
                if move.product_uom.id != rec.product_id.uom_id.id:
                    product_qty += move.product_uom._compute_quantity(move.quantity_done, rec.product_id.uom_id, rounding_method='HALF-UP')
                else:
                    product_qty += move.quantity_done
            rec.quantity_onhand = rec.quantity - product_qty
