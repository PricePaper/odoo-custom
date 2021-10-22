# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from operator import itemgetter
from itertools import groupby
from odoo.tools.float_utils import float_compare, float_round, float_is_zero

class StockMove(models.Model):
    _inherit = "stock.move"

    picking_status = fields.Char(string='Picking Status', compute='_compute_picking_state')
    delivery_notes = fields.Text(string='Delivery Notes', related='partner_id.delivery_notes')
    delivery_move_id = fields.Many2one('stock.move', string='Delivery for Move')
    delivery_picking_id = fields.Many2one('stock.picking', string='Delivery for Picking', readonly=True,
                                          related='delivery_move_id.picking_id')
    is_transit = fields.Boolean(string='Transit')
    qty_update = fields.Float(String="Reset Logic")
    qty_available = fields.Float(String="Available Quantity", compute='_compute_qty_available')
    partner_id = fields.Many2one('res.partner', compute='_compute_partner_id', string="Partner", readonly=True)
    reason_id = fields.Many2one('stock.picking.return.reason', string='Reason  For Return (Stock)')
    qty_to_transfer = fields.Float(String="Qty in Location", compute='_compute_qty_to_transfer', store=False)
    unit_price = fields.Float(string="Unit Price", copy=False, compute='_compute_total_price', store=False)
    total = fields.Float(string="Subtotal", copy=False, compute='_compute_total_price', store=False)

    @api.multi
    def _run_valuation(self, quantity=None):
        # Extend `_run_valuation` to make it work on return receipt moves.
        self.ensure_one()
        value_to_return = 0
        if self._is_out() and self.picking_id.is_return:
            origin_move = self.origin_returned_move_id
            valued_move_lines = self.move_line_ids.filtered(lambda ml: ml.location_id._should_be_valued() and not ml.location_dest_id._should_be_valued() and not ml.owner_id)
            valued_quantity = 0
            for valued_move_line in valued_move_lines:
                valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, self.product_id.uom_id)

            # Note: we always compute the fifo `remaining_value` and `remaining_qty` fields no
            # matter which cost method is set, to ease the switching of cost method.
            if origin_move.remaining_qty < valued_quantity:
                value_to_return = super(StockMove, self)._run_valuation(quantity)
            else:
                vals = {}
                price_unit = self._get_price_unit()
                price_unit = -price_unit
                value = price_unit * (quantity or valued_quantity)
                value_to_return = value if quantity is None or not self.value else self.value
                vals = {
                    'price_unit': price_unit,
                    'value': value_to_return,
                }
                if self.product_id.cost_method == 'standard':
                    value = self.product_id.standard_price * (quantity or valued_quantity)
                    value_to_return = value if quantity is None or not self.value else self.value
                    vals.update({
                        'price_unit': self.product_id.standard_price,
                        'value': value_to_return,
                    })
                self.write(vals)
                origin_move.write({
                    'remaining_qty': origin_move.remaining_qty - valued_quantity,
                    'remaining_value': origin_move.remaining_value + value_to_return
                })
        else:
            value_to_return = super(StockMove, self)._run_valuation(quantity)
        return value_to_return

    def receipt_move_price_fix_search(self):
        picking_lines = self.env['stock.picking'].search(
                [('picking_type_code', '=', 'incoming'), ('state', '!=', 'cancel')]).mapped(
                'move_ids_without_package').filtered(
                lambda r: r.purchase_line_id and r.purchase_line_id.price_unit != r.price_unit)
        picking = picking_lines.mapped('picking_id')
        return picking_lines.ids or False

    def receipt_move_price_fix(self):
        self.price_unit = self.purchase_line_id.price_unit
        return True



    def _create_account_move_line(self, credit_account_id, debit_account_id, journal_id):
        self.ensure_one()
        if self.picking_id.transit_date:
            super(StockMove, self.with_context(force_period_date=self.picking_id.transit_date))._create_account_move_line(credit_account_id, debit_account_id, journal_id)
        else:
            super(StockMove,self)._create_account_move_line(credit_account_id, debit_account_id, journal_id)

    @api.model
    def _run_fifo(self, move, quantity=None):
        """ Value `move` according to the FIFO rule, meaning we consume the
        oldest receipt first. Candidates receipts are marked consumed or free
        thanks to their `remaining_qty` and `remaining_value` fields.
        By definition, `move` should be an outgoing stock move.

        :param quantity: quantity to value instead of `move.product_qty`
        :returns: valued amount in absolute

        Override to remove product cost update
        """
        move.ensure_one()

        # Deal with possible move lines that do not impact the valuation.
        valued_move_lines = move.move_line_ids.filtered(lambda ml: ml.location_id._should_be_valued() and not ml.location_dest_id._should_be_valued() and not ml.owner_id)
        valued_quantity = 0
        for valued_move_line in valued_move_lines:
            valued_quantity += valued_move_line.product_uom_id._compute_quantity(valued_move_line.qty_done, move.product_id.uom_id)

        # Find back incoming stock moves (called candidates here) to value this move.
        qty_to_take_on_candidates = quantity or valued_quantity
        candidates = move.product_id._get_fifo_candidates_in_move_with_company(move.company_id.id)
        if move.is_storage_contract and move.sale_line_id and move.sale_line_id.storage_contract_line_id and \
        move.sale_line_id.storage_contract_line_id.order_id.id not in [99088,99087,99086,99085,99084,99083,99080,99079,99077,99076,99074,99073,99072,99071,99070,99075,105208,105207,105206]:
            candidates = move.sale_line_id and move.sale_line_id.storage_contract_line_id and \
            move.sale_line_id.storage_contract_line_id.purchase_line_ids.mapped('move_ids')
            if sum(candidates.mapped('remaining_qty')) <= 0:
                raise UserError("There is no quantity remaining in original order")
        else:
            remove = candidates.filtered(lambda rec: rec.is_storage_contract is True)
            candidates -= remove
        new_standard_price = 0
        tmp_qty = 0
        tmp_value = 0  # to accumulate the value taken on the candidates
        for candidate in candidates:
            new_standard_price = candidate.price_unit
            if candidate.remaining_qty <= qty_to_take_on_candidates:
                qty_taken_on_candidate = candidate.remaining_qty
            else:
                qty_taken_on_candidate = qty_to_take_on_candidates

            # As applying a landed cost do not update the unit price, naivelly doing
            # something like qty_taken_on_candidate * candidate.price_unit won't make
            # the additional value brought by the landed cost go away.
            candidate_price_unit = candidate.remaining_value / (candidate.remaining_qty if candidate.remaining_qty else 1)
            value_taken_on_candidate = qty_taken_on_candidate * candidate_price_unit
            candidate_vals = {
                'remaining_qty': candidate.remaining_qty - qty_taken_on_candidate,
                'remaining_value': candidate.remaining_value - value_taken_on_candidate,
            }
            candidate.write(candidate_vals)

            qty_to_take_on_candidates -= qty_taken_on_candidate
            tmp_qty += qty_taken_on_candidate
            tmp_value += value_taken_on_candidate
            if qty_to_take_on_candidates == 0:
                break

        # Update the standard price with the price of the last used candidate, if any.
        # if new_standard_price and move.product_id.cost_method == 'fifo':
        #     move.product_id.sudo().with_context(force_company=move.company_id.id) \
        #         .standard_price = new_standard_price

        # If there's still quantity to value but we're out of candidates, we fall in the
        # negative stock use case. We chose to value the out move at the price of the
        # last out and a correction entry will be made once `_fifo_vacuum` is called.
        if qty_to_take_on_candidates == 0:
            # If the move is not valued yet we compute the price_unit based on the value taken on
            # the candidates.
            # If the move has already been valued, it means that we editing the qty_done on the
            # move. In this case, the price_unit computation should take into account the quantity
            # already valued and the new quantity taken.
            if not move.value:
                price_unit = -tmp_value / (move.product_qty or quantity)
            else:
                price_unit = (-(tmp_value) + move.value) / (tmp_qty + move.product_qty)
            move.write({
                'value': -tmp_value if not quantity else move.value or -tmp_value,  # outgoing move are valued negatively
                'price_unit': price_unit,
            })
        elif qty_to_take_on_candidates > 0:
            last_fifo_price = new_standard_price or move.product_id.standard_price
            negative_stock_value = last_fifo_price * -qty_to_take_on_candidates
            tmp_value += abs(negative_stock_value)
            vals = {
                'remaining_qty': move.remaining_qty + -qty_to_take_on_candidates,
                'remaining_value': move.remaining_value + negative_stock_value,
                'value': -tmp_value,
                'price_unit': -1 * last_fifo_price,
            }
            move.write(vals)
        return tmp_value

    @api.depends('quantity_done')
    def _compute_total_price(self):
        for move in self:
            if move.picking_id.picking_type_id.code == 'outgoing':
                move.unit_price = -move.price_unit
            elif move.picking_id.picking_type_id.code == 'incoming':
                move.unit_price = move.price_unit
            if move.state != 'cancel':
                move.total = move.unit_price * move.quantity_done

    @api.depends('sale_line_id.order_id.partner_shipping_id')
    def _compute_partner_id(self):
        for move in self:
            move.partner_id = move.sale_line_id.order_id.partner_shipping_id

    @api.depends('product_id', 'picking_id.location_id')
    def _compute_qty_to_transfer(self):
        quant = self.env['stock.quant']
        for move in self:
            if move.product_id and move.picking_id and move.picking_id.location_id:
                quant = quant.search([('product_id', '=', move.product_id.id), ('location_id', '=', move.picking_id.location_id.id)], limit=1)
                if quant:
                    qty = quant.quantity - quant.reserved_quantity
                    move.qty_to_transfer = move.product_id.uom_id._compute_quantity(qty, move.product_uom, rounding_method='HALF-UP')
                else:
                    move.qty_to_transfer = 0
            else:
                move.qty_to_transfer = 0

    @api.onchange('product_id')
    def onchange_product_id(self):
        res = super(StockMove, self).onchange_product_id()
        if self.picking_id and self.picking_id.is_internal_transfer:
            if self.product_id:
                product_loc_id = self.product_id.property_stock_location.id or self.product_id.categ_id.property_stock_location.id or ''
                self.location_dest_id = product_loc_id
                self.location_id = self.picking_id.location_id and self.picking_id.location_id or False
            else:
                self.location_dest_id = False

    def _compute_qty_available(self):
        quant = self.env['stock.quant']
        for move in self:
            qty = quant._get_available_quantity(product_id=move.product_id, location_id=move.location_id)
            move.qty_available = move.product_id.uom_id._compute_quantity(qty, move.product_uom, rounding_method='HALF-UP')

    @api.multi
    def _compute_picking_state(self):
        for move in self:
            move.picking_status = move.picking_id and move.picking_id.state or ''

    def _action_assign_reset_qty(self):
        """ Reserve stock moves by creating their stock move lines. A stock move is
                considered reserved once the sum of `product_qty` for all its move lines is
                equal to its `product_qty`. If it is less, the stock move is considered
                partially available.
                """
        assigned_moves = self.env['stock.move']
        partially_available_moves = self.env['stock.move']
        # Read the `reserved_availability` field of the moves out of the loop to prevent unwanted
        # cache invalidation when actually reserving the move.
        reserved_availability = {move: move.reserved_availability for move in self}
        roundings = {move: move.product_id.uom_id.rounding for move in self}
        move_line_vals_list = []
        for move in self.filtered(lambda m: m.state in ['assigned', 'confirmed', 'waiting', 'partially_available']):
            rounding = roundings[move]
            missing_reserved_uom_quantity = move.qty_update - reserved_availability[move]
            missing_reserved_quantity = move.product_uom._compute_quantity(missing_reserved_uom_quantity,
                                                                           move.product_id.uom_id,
                                                                           rounding_method='HALF-UP')

            if move.location_id.should_bypass_reservation() \
                    or move.product_id.type == 'consu':
                # create the move line(s) but do not impact quants
                if move.product_id.tracking == 'serial' and (
                        move.picking_type_id.use_create_lots or move.picking_type_id.use_existing_lots):
                    for i in range(0, int(missing_reserved_quantity)):
                        move_line_vals_list.append(move._prepare_move_line_vals(quantity=1))
                else:
                    to_update = move.move_line_ids.filtered(lambda ml: ml.product_uom_id == move.product_uom and
                                                                       ml.location_id == move.location_id and
                                                                       ml.location_dest_id == move.location_dest_id and
                                                                       ml.picking_id == move.picking_id and
                                                                       not ml.lot_id and
                                                                       not ml.package_id and
                                                                       not ml.owner_id)
                    if to_update:
                        to_update[0].product_uom_qty += missing_reserved_uom_quantity
                    else:
                        move_line_vals_list.append(move._prepare_move_line_vals(quantity=missing_reserved_quantity))
                assigned_moves |= move
            else:
                if not move.move_orig_ids:
                    if move.procure_method == 'make_to_order':
                        continue
                    # If we don't need any quantity, consider the move assigned.
                    need = missing_reserved_quantity
                    if float_is_zero(need, precision_rounding=rounding):
                        assigned_moves |= move
                        continue
                    # Reserve new quants and create move lines accordingly.
                    forced_package_id = move.package_level_id.package_id or None
                    available_quantity = float_round(self.env['stock.quant']._get_available_quantity(move.product_id,
                                                                                         move.location_id,
                                                                                         package_id=forced_package_id), precision_digits=2)
                    if available_quantity <= 0:
                        continue
                    taken_quantity = move._update_reserved_quantity(need, available_quantity, move.location_id,
                                                                    package_id=forced_package_id, strict=False)
                    if float_is_zero(taken_quantity, precision_rounding=rounding):
                        continue
                    if float_compare(need, taken_quantity, precision_rounding=rounding) == 0:
                        assigned_moves |= move
                    else:
                        partially_available_moves |= move

                else:
                    # Check what our parents brought and what our siblings took in order to
                    # determine what we can distribute.
                    # `qty_done` is in `ml.product_uom_id` and, as we will later increase
                    # the reserved quantity on the quants, convert it here in
                    # `product_id.uom_id` (the UOM of the quants is the UOM of the product).
                    move_lines_in = move.move_orig_ids.filtered(lambda m: m.state == 'done').mapped('move_line_ids')
                    keys_in_groupby = ['location_dest_id', 'lot_id', 'result_package_id', 'owner_id']

                    def _keys_in_sorted(ml):
                        return (ml.location_dest_id.id, ml.lot_id.id, ml.result_package_id.id, ml.owner_id.id)

                    grouped_move_lines_in = {}
                    for k, g in groupby(sorted(move_lines_in, key=_keys_in_sorted), key=itemgetter(*keys_in_groupby)):
                        qty_done = 0
                        for ml in g:
                            qty_done += ml.product_uom_id._compute_quantity(ml.qty_done, ml.product_id.uom_id)
                        grouped_move_lines_in[k] = qty_done
                    move_lines_out_done = (move.move_orig_ids.mapped('move_dest_ids') - move) \
                        .filtered(lambda m: m.state in ['done']) \
                        .mapped('move_line_ids')
                    # As we defer the write on the stock.move's state at the end of the loop, there
                    # could be moves to consider in what our siblings already took.
                    moves_out_siblings = move.move_orig_ids.mapped('move_dest_ids') - move
                    moves_out_siblings_to_consider = moves_out_siblings & (assigned_moves + partially_available_moves)
                    reserved_moves_out_siblings = moves_out_siblings.filtered(
                        lambda m: m.state in ['partially_available', 'assigned'])
                    move_lines_out_reserved = (reserved_moves_out_siblings | moves_out_siblings_to_consider).mapped(
                        'move_line_ids')
                    keys_out_groupby = ['location_id', 'lot_id', 'package_id', 'owner_id']

                    def _keys_out_sorted(ml):
                        return (ml.location_id.id, ml.lot_id.id, ml.package_id.id, ml.owner_id.id)

                    grouped_move_lines_out = {}
                    for k, g in groupby(sorted(move_lines_out_done, key=_keys_out_sorted),
                                        key=itemgetter(*keys_out_groupby)):
                        qty_done = 0
                        for ml in g:
                            qty_done += ml.product_uom_id._compute_quantity(ml.qty_done, ml.product_id.uom_id)
                        grouped_move_lines_out[k] = qty_done
                    for k, g in groupby(sorted(move_lines_out_reserved, key=_keys_out_sorted),
                                        key=itemgetter(*keys_out_groupby)):
                        grouped_move_lines_out[k] = sum(
                            self.env['stock.move.line'].concat(*list(g)).mapped('product_qty'))
                    available_move_lines = {key: grouped_move_lines_in[key] - grouped_move_lines_out.get(key, 0) for key
                                            in grouped_move_lines_in.keys()}
                    # pop key if the quantity available amount to 0
                    available_move_lines = dict((k, v) for k, v in available_move_lines.items() if v)

                    if not available_move_lines:
                        continue
                    for move_line in move.move_line_ids.filtered(lambda m: m.product_qty):
                        if available_move_lines.get((move_line.location_id, move_line.lot_id,
                                                     move_line.result_package_id, move_line.owner_id)):
                            available_move_lines[(move_line.location_id, move_line.lot_id, move_line.result_package_id,
                                                  move_line.owner_id)] -= move_line.product_qty
                    for (location_id, lot_id, package_id, owner_id), quantity in available_move_lines.items():
                        need = move.product_qty - sum(move.move_line_ids.mapped('product_qty'))
                        # `quantity` is what is brought by chained done move lines. We double check
                        # here this quantity is available on the quants themselves. If not, this
                        # could be the result of an inventory adjustment that removed totally of
                        # partially `quantity`. When this happens, we chose to reserve the maximum
                        # still available. This situation could not happen on MTS move, because in
                        # this case `quantity` is directly the quantity on the quants themselves.
                        available_quantity = self.env['stock.quant']._get_available_quantity(
                            move.product_id, location_id, lot_id=lot_id, package_id=package_id, owner_id=owner_id,
                            strict=True)
                        if float_is_zero(available_quantity, precision_rounding=rounding):
                            continue
                        taken_quantity = move._update_reserved_quantity(need, min(quantity, available_quantity),
                                                                        location_id, lot_id, package_id, owner_id)
                        if float_is_zero(taken_quantity, precision_rounding=rounding):
                            continue
                        if float_is_zero(need - taken_quantity, precision_rounding=rounding):
                            assigned_moves |= move
                            break
                        partially_available_moves |= move
        self.env['stock.move.line'].create(move_line_vals_list)
        partially_available_moves.write({'state': 'partially_available'})
        assigned_moves.write({'state': 'assigned'})
        self.mapped('picking_id')._check_entire_pack()

    @api.multi
    def action_reset(self):
        """
        Reset the reserved quantity with reset logic values.
        Negative value for decrease,
        Positive value for increase.
        """

        for move in self:
            # qty_available always shows the quanity in requested (UOM).
            move._do_unreserve()
            available_qty = move.qty_available
            if available_qty <= 0 and move.qty_update > 0:
                raise UserError(_(
                    'It is not possible to reserve more products of %s than you have in stock.') % move.product_id.display_name)
            elif move.reserved_availability <= 0 and move.qty_update < 0:
                raise UserError(_(
                    'It is not possible to unreserve more products of %s than you have in stock.') % move.product_id.display_name)
            elif move.qty_available < move.qty_update:
                raise UserError(_('Choose a value less than available quantity.'))
            elif move.qty_update < 0 and move.reserved_availability < abs(move.qty_update):
                raise UserError(_('Not enough reserved quantity..!'))
            elif move.product_uom_qty < move.qty_update:
                raise UserError(_("Can't reserve more product than requested..!"))
            else:
                move._action_assign_reset_qty()
                if move.is_transit:
                    move.quantity_done = move.reserved_availability


    def action_cancel_move(self):
        self._action_cancel()
        return True

    def action_cancel_popup(self):
        return {
            'name': 'Cancel Move',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_id': self.env.ref('batch_delivery.view_stock_move_cancel_window').id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    @api.multi
    def action_show_reset_window(self):
        self.ensure_one()
        self.qty_update = 0
        return {
            'name': 'Reset Logic',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_id': self.env.ref('batch_delivery.view_stock_move_rest_window').id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        """updates the move line values
           with preferred lot id
        """
        res = super(StockMove, self)._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        if self.sale_line_id and self.sale_line_id.lot_id:
            res.update({'pref_lot_id': self.sale_line_id.lot_id.id})
        return res

    def _update_reserved_quantity(self, need, available_quantity, location_id, lot_id=None, package_id=None,
                                  owner_id=None, strict=True):
        """if a lot is preffered then use that lot for reserving the stock move
           also check the quantities currently available for that lot in doing so.
        """
        if self.sale_line_id and self.sale_line_id.lot_id:
            avail_qty = self.sale_line_id.lot_id.product_qty
            if avail_qty > self.sale_line_id.product_uom_qty:
                lot_id = self.sale_line_id.lot_id
        res = super(StockMove, self)._update_reserved_quantity(need, available_quantity, location_id, lot_id=lot_id,
                                                               package_id=package_id, owner_id=owner_id, strict=strict)
        return res


StockMove()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
