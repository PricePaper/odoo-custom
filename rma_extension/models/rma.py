from odoo import fields, models, api
from odoo.exceptions import ValidationError

class RMARetMerAuth(models.Model):
    _inherit = 'rma.ret.mer.auth'


    @api.onchange('sale_order_id')
    def onchange_sale_order_id(self):
        order_line_lst = []
        for order_line in self.sale_order_id.order_line:
            rma_sale_line = (0, 0, {
                'product_id': order_line.product_id and
                              order_line.product_id.id or False,
                'total_qty': order_line.product_uom_qty or 0,
                'delivered_quantity': order_line.qty_delivered,
                'order_quantity': order_line.product_uom_qty or 0,
                'refund_qty': order_line.qty_delivered,
                'refund_price': order_line.price_unit,
                'price_unit': order_line.price_unit or 0,
                'price_subtotal': order_line.price_subtotal or 0,
                'source_location_id':
                    self.env.user.company_id.source_location_id.id or
                    False,
                'destination_location_id': self.env.user.company_id.
                             destination_location_id.id or False,
                'type': 'return',
                'tax_id': order_line.tax_id,
                'so_line_id': order_line.id
            })
            order_line_lst.append(rma_sale_line)
        self.rma_sale_lines_ids = [(5,)]
        self.rma_sale_lines_ids = order_line_lst

    @api.onchange('purchase_order_id')
    def onchange_purchase_order_id(self):
        po_line_lst = []
        dest_location = self.env['stock.location'].search([('usage', '=', 'supplier')], limit=1)
        for order_line in self.purchase_order_id.order_line:
            rma_purchase_line = (0, 0, {
                'product_id': order_line.product_id and
                              order_line.product_id.id or False,
                'total_qty': order_line.product_uom_qty or 0,
                'refund_qty': order_line.qty_received or 0,
                'refund_price': order_line.price_unit,
                'order_quantity': order_line.product_qty or 0,
                'delivered_quantity': order_line.qty_received,
                'total_price': order_line.price_total,
                'price_unit': order_line.price_unit or 0,
                'source_location_id':
                    self.env.user.company_id.source_location_id.id or
                    False,
                'destination_location_id': dest_location and dest_location.id or
                    self.env.user.company_id.destination_location_id.id or
                    False,
                'type': 'return',
                'tax_id': order_line.taxes_id,
                'po_line_id': order_line.id
            })
            po_line_lst.append(rma_purchase_line)
        self.rma_purchase_lines_ids = [(5,)]
        self.rma_purchase_lines_ids = po_line_lst

    @api.multi
    def create_receive_picking(self):
        """
        Create Receive picking for RMA Customer and set RMA state to.

           resolved. Create refund invoices for return type RMA.
        """
        for rma in self:
            if rma.rma_type == 'customer':
                state = 'resolved'
                exchange_move_vals = []
                stock_moves_vals = []
                invoice_line_vals = []
                exchange_inv_line_vals = []
                for rma_line in rma.rma_sale_lines_ids:
                    state = 'approve'
                    rma_move_vals_b2b = {
                        'product_id': rma_line.product_id and
                        rma_line.product_id.id or False,
                        'name': rma_line.product_id and
                        rma_line.product_id.name or False,
                        'origin': rma.name,
                        'product_uom_qty': rma_line.refund_qty or 0,
                        'location_id': rma_line.source_location_id.id or False,
                        'location_dest_id':
                        rma_line.destination_location_id.id or
                        False,
                        'product_uom': rma_line.product_id.uom_id and
                        rma_line.product_id.uom_id.id or False,
                        'rma_id': rma.id,
                        'group_id': rma.sale_order_id.procurement_group_id.id,
                        'price_unit': rma_line.price_subtotal or 0,
                        'sale_line_id': rma_line.so_line_id.id,
                        'to_refund': True
                    }
                    stock_moves_vals.append((0, 0, rma_move_vals_b2b))
                    inv_account_id = rma_line.product_id. \
                        property_account_income_id and \
                        rma_line.product_id. \
                        property_account_income_id.id or \
                        rma_line.product_id.categ_id. \
                        property_account_income_categ_id and \
                        rma_line.product_id.categ_id. \
                        property_account_income_categ_id.id or False
                    if not inv_account_id:
                        raise ValidationError((
                            'No account defined for product "%s".') %
                            rma_line.product_id.name)
                    prod_price = 0.0
                    if rma_line.refund_qty != 0:
                        prod_price = float(
                            (rma_line.refund_price) / float(
                                rma_line.refund_qty))
                    inv_line_values = {
                        'product_id': rma_line.product_id and rma_line.
                        product_id.id or False,
                        'account_id': inv_account_id or False,
                        'name': rma_line.product_id and rma_line.
                        product_id.name or False,
                        'quantity': rma_line.refund_qty or 0,
                        'price_unit': prod_price or 0,
                        'currency_id': rma.currency_id.id or False,
                        'sale_line_ids': [(6, 0, [rma_line.so_line_id.id])]
                    }

                    if rma_line.tax_id and rma_line.tax_id.ids:
                        inv_line_values.update(
                            {'invoice_line_tax_ids': [(6, 0, rma_line.
                                                       tax_id.ids)]})

                    invoice_line_vals.append((0, 0, inv_line_values))

                    if rma_line.type == 'exchange':
                        state = 'approve'
                        rma_move_vals_b2c = {
                            'product_id': rma_line.exchange_product_id and
                            rma_line.exchange_product_id.id or False,
                            'name': rma_line.exchange_product_id and
                            rma_line.exchange_product_id.name or False,
                            'origin': rma.name,
                            'product_uom_qty': rma_line.refund_qty or 0,
                            'location_id':
                            rma_line.destination_location_id.id or
                            False,
                            'location_dest_id':
                            rma_line.source_location_id.id or
                            False,
                            'product_uom':
                            rma_line.exchange_product_id.uom_id and
                            rma_line.exchange_product_id.uom_id.id or False,
                            'rma_id': rma.id,
                            'group_id':
                            rma.sale_order_id.procurement_group_id.id,
                            'price_unit': rma_line.price_subtotal or 0,
                        }
                        exchange_move_vals.append((0, 0, rma_move_vals_b2c))
                        inv_line_vals_exchange = {
                            'product_id': rma_line.exchange_product_id and
                            rma_line.exchange_product_id.id or False,
                            'account_id': inv_account_id or False,
                            'name': rma_line.exchange_product_id and rma_line.
                            exchange_product_id.name or False,
                            'quantity': rma_line.refund_qty or 0,
                            'price_unit':
                            rma_line.exchange_product_id.lst_price or 0,
                            'currency_id': rma.currency_id.id or False,
                        }
                        exchange_inv_line_vals.append(
                            (0, 0, inv_line_vals_exchange))

                        if rma_line.tax_id and rma_line.tax_id.ids:
                            inv_line_vals_exchange.update(
                                {'invoice_line_tax_ids': [(6, 0, rma_line.
                                                           tax_id.ids)]})

                            exchange_inv_line_vals.append(
                                (0, 0, inv_line_vals_exchange))
                for move in stock_moves_vals:
                    picking = self.env['stock.picking'].search([
                        ('rma_id', '=', rma.id),
                        ('location_id', '=', move[2]['location_id']),
                        ('location_dest_id', '=',
                         move[2]['location_dest_id'])])
                    if not picking:
                        picking_type_id = self.env[
                            'stock.picking.type'].search([
                                ('code', '=', 'incoming'),
                                ('warehouse_id.company_id', 'in',
                                 [self.env.context.get(
                                     'company_id',
                                     self.env.user.company_id.id),
                                  False])],
                            limit=1).id
                        picking_vals = {
                            'move_type': 'one',
                            'picking_type_id': picking_type_id or False,
                            'partner_id': rma.partner_id and
                            rma.partner_id.id or
                            False,
                            'origin': rma.name,
                            'move_lines': [move],
                            'location_id': move[2]['location_id'],
                            'location_dest_id': move[2]['location_dest_id'],
                            'rma_id': rma.id,
                        }
                        picking_rec = self.env[
                            'stock.picking'].create(picking_vals)
                        picking_rec.action_confirm()
                        picking_rec.action_assign()

                    else:
                        move[2]['picking_id'] = picking.id
                        self.env['stock.move'].create(move[2])
                for vals in exchange_move_vals:
                    ex_picking = self.env['stock.picking'].search([
                        ('rma_id', '=', rma.id),
                        ('location_id', '=', vals[2]['location_id']),
                        ('location_dest_id', '=', vals[2]['location_dest_id']),
                        ('picking_type_code', '=', 'outgoing')])
                    if not ex_picking:
                        picking_type = self.env['stock.picking.type'].search([
                            ('code', '=', 'outgoing'),
                            ('warehouse_id.company_id', 'in',
                             [self.env.context.get('company_id',
                                                   self.env.user.company_id.id
                                                   ),
                              False])],
                            limit=1).id
                        exchange_picking_vals = {
                            'move_type': 'one',
                            'picking_type_id': picking_type or False,
                            'partner_id': rma.partner_id and
                            rma.partner_id.id or
                            False,
                            'origin': rma.name,
                            'move_lines': [vals],
                            'location_id': vals[2]['location_id'],
                            'location_dest_id': vals[2]['location_dest_id'],
                            'rma_id': rma.id,
                        }
                        picking_rec_ex = self.env[
                            'stock.picking'].create(exchange_picking_vals)
                        picking_rec_ex.action_confirm()
                        picking_rec_ex.action_assign()
                    else:
                        vals[2]['picking_id'] = ex_picking.id
                        self.env['stock.move'].create(vals[2])
                if invoice_line_vals:
                    inv_values = {
                        'type': 'out_refund',
                        'origin': rma.name or '',
                        'name': rma.name or '',
                        'comment': rma.problem or '',
                        'partner_id': rma.partner_id and
                        rma.partner_id.id or False,
                        'account_id':
                        rma.partner_id.property_account_receivable_id and
                        rma.partner_id.property_account_receivable_id.id or
                        False,
                        'invoice_line_ids': invoice_line_vals,
                        'date_invoice': rma.rma_date or False,
                        'rma_id': rma.id,
                    }
                    self.env['account.invoice'].create(inv_values)

                if exchange_inv_line_vals:
                    ex_inv_vals = {
                        'type': 'out_invoice',
                        'comment': rma.problem or '',
                        'origin': rma.name or '',
                        'name': rma.name or '',
                        'partner_id': rma.partner_id and
                        rma.partner_id.id or False,
                        'account_id':
                        rma_line.exchange_product_id.
                        property_account_expense_id and
                        rma_line.exchange_product_id.
                        property_account_expense_id.id or
                        False,
                        'invoice_line_ids': exchange_inv_line_vals,
                        'date_invoice': rma.rma_date or False,
                        'rma_id': rma.id,
                    }
                    self.env['account.invoice'].create(ex_inv_vals)
                rma.write({'state': state})
            elif rma.rma_type == 'supplier':
                state = 'resolved'
                exchange_moves = []
                moves_vals = []
                invoice_vals = []
                supp_inv_line_vals = []
                for line in rma.rma_purchase_lines_ids:
                    state = 'approve'
                    pol = line.po_line_id
                    rma_move_vals = {
                        'product_id': line.product_id and
                        line.product_id.id or False,
                        'name': line.product_id and
                        line.product_id.name or False,
                        'origin': rma.name,
                        'group_id': rma.purchase_order_id.group_id.id,
                        'product_uom_qty': line.refund_qty or 0,
                        'location_id': line.source_location_id.id or
                        False,
                        'location_dest_id': line.destination_location_id.id or
                        False,
                        'product_uom': line.product_id.uom_id and
                        line.product_id.uom_id.id or False,
                        'rma_id': rma.id,
                        'price_unit': line.price_subtotal or 0,
                        'to_refund': True,
                        'purchase_line_id': pol.id
                    }
                    moves_vals.append((0, 0, rma_move_vals))
                    inv_ex_account_id = line.product_id. \
                        property_account_expense_id and \
                        line.product_id. \
                        property_account_expense_id.id or \
                        line.product_id.categ_id. \
                        property_account_expense_categ_id and \
                        line.product_id.categ_id. \
                        property_account_expense_categ_id.id or False
                    if not inv_ex_account_id:
                        raise ValidationError((
                            'No account defined for product "%s".') %
                            line.product_id.name)
                    prod_price = 0.0
                    if line.refund_qty != 0:
                        prod_price = float(
                            (line.refund_price) / float(
                                line.refund_qty))
                    inv_line_vals = {
                        'product_id': line.product_id and line.
                        product_id.id or False,
                        'account_id': inv_ex_account_id or False,
                        'name': line.product_id and line.
                        product_id.name or False,
                        'quantity': line.refund_qty or 0,
                        'price_unit': prod_price or 0,
                        'currency_id': rma.currency_id.id or False,
                        'purchase_line_id': line.po_line_id.id
                    }
                    if line.tax_id and line.tax_id.ids:
                        inv_line_vals.update(
                            {'invoice_line_tax_ids': [(6, 0, line.
                                                       tax_id.ids)]})
                    invoice_vals.append((0, 0, inv_line_vals))
                    if line.type == 'exchange':
                        state = 'approve'
                        rma_move_vals_ex = {
                            'product_id': line.exchange_product_id and
                            line.exchange_product_id.id or False,
                            'name': line.exchange_product_id and
                            line.exchange_product_id.name or False,
                            'origin': rma.name,
                            'purchase_line_id': pol.id or False,
                            'group_id': rma.purchase_order_id.group_id.id,
                            'product_uom_qty': line.refund_qty or 0,
                            'location_id': line.source_location_id.id or
                            False,
                            'location_dest_id':
                            line.destination_location_id.id or
                            False,
                            'product_uom': line.exchange_product_id.uom_id and
                            line.exchange_product_id.uom_id.id or False,
                            'rma_id': rma.id,
                            'price_unit': line.price_subtotal or 0,
                        }
                        exchange_moves.append((0, 0, rma_move_vals_ex))
                        supp = self.env['product.supplierinfo'].search([
                            ('product_id', '=', line.exchange_product_id.id),
                            ('name', '=', rma.supplier_id.id)])
                        inv_line_vals_supp = {
                            'product_id': line.exchange_product_id and
                            line.exchange_product_id.id or False,
                            'account_id': inv_ex_account_id or False,
                            'name': line.exchange_product_id and
                            line.exchange_product_id.name or False,
                            'quantity': line.refund_qty or 0,
                            'price_unit': supp.price or 0,
                            'currency_id': rma.currency_id.id or False,
                        }
                        supp_inv_line_vals.append((0, 0, inv_line_vals_supp))

                        if line.tax_id and line.tax_id.ids:
                            inv_line_vals_supp.update(
                                {'invoice_line_tax_ids': [(6, 0, line.
                                                           tax_id.ids)]})

                            supp_inv_line_vals.append(
                                (0, 0, inv_line_vals_supp))
                for move in moves_vals:
                    picking = self.env['stock.picking'].search([
                        ('rma_id', '=', rma.id),
                        ('location_id', '=', move[2]['location_id']),
                        ('location_dest_id', '=',
                         move[2]['location_dest_id'])])
                    if not picking:
                        picking_type_id = self.env[
                            'stock.picking.type'].search([
                                ('code', '=', 'outgoing'),
                                ('warehouse_id.company_id', 'in',
                                 [self.env.context.get(
                                     'company_id',
                                     self.env.user.company_id.id),
                                     False])],
                            limit=1).id
                        picking_re_vals = {
                            'move_type': 'one',
                            'picking_type_id': picking_type_id or False,
                            'partner_id': rma.supplier_id and
                            rma.supplier_id.id or
                            False,
                            'origin': rma.name,
                            'move_lines': [move],
                            'location_id': move[2]['location_id'],
                            'location_dest_id': move[2]['location_dest_id'],
                            'rma_id': rma.id,
                        }
                        picking_rec_re = self.env[
                            'stock.picking'].create(picking_re_vals)
                        picking_rec_re.action_confirm()
                        picking_rec_re.action_assign()

                    else:
                        move[2]['picking_id'] = picking.id
                        self.env['stock.move'].create(move[2])
                for vals in exchange_moves:
                    ex_picking = self.env['stock.picking'].search([
                        ('rma_id', '=', rma.id),
                        ('location_id', '=', vals[2]['location_id']),
                        ('location_dest_id', '=', vals[2]['location_dest_id']),
                        ('picking_type_code', '=', 'incoming')])
                    if not ex_picking:
                        picking_type = self.env['stock.picking.type'].search([
                            ('code', '=', 'incoming'),
                            ('warehouse_id.company_id', 'in',
                             [self.env.context.get(
                                 'company_id',
                                 self.env.user.company_id.id),
                              False])],
                            limit=1).id
                        exchange_vals = {
                            'move_type': 'one',
                            'picking_type_id': picking_type or False,
                            'partner_id': rma.supplier_id and
                            rma.supplier_id.id or
                            False,
                            'origin': rma.name,
                            'move_lines': [vals],
                            'location_id': vals[2]['location_id'],
                            'location_dest_id': vals[2]['location_dest_id'],
                            'rma_id': rma.id,
                        }
                        picking_rec_exchange = self.env[
                            'stock.picking'].create(exchange_vals)
                        picking_rec_exchange.action_confirm()
                        picking_rec_exchange.action_assign()
                    else:
                        vals[2]['picking_id'] = ex_picking.id
                        self.env['stock.move'].create(vals[2])
                if invoice_vals:
                    inv_values = {
                        'type': 'in_refund',
                        'name': rma.name or '',
                        'origin': rma.name or '',
                        'comment': rma.problem or '',
                        'partner_id': rma.supplier_id and
                        rma.supplier_id.id or False,
                        'account_id':
                        rma.supplier_id.property_account_receivable_id and
                        rma.supplier_id.property_account_receivable_id.id or
                        False,
                        'invoice_line_ids': invoice_vals,
                        'date_invoice': rma.rma_date or False,
                        'rma_id': rma.id
                    }
                    self.env['account.invoice'].create(inv_values)

                if supp_inv_line_vals:
                    ex_supp_inv_vals = {
                        'type': 'in_invoice',
                        'name': rma.name or '',
                        'comment': rma.problem or '',
                        'origin': rma.name or '',
                        'partner_id': rma.supplier_id and
                        rma.supplier_id.id or False,
                        'account_id':
                        rma.supplier_id.property_account_payable_id and
                        rma.supplier_id.property_account_payable_id.id or
                        False,
                        'invoice_line_ids': supp_inv_line_vals,
                        'date_invoice': rma.rma_date or False,
                        'rma_id': rma.id,
                    }
                    self.env['account.invoice'].create(ex_supp_inv_vals)
                rma.write({'state': state})
            else:
                state = 'resolved'
                exchange_move_vals = []
                stock_moves_vals = []
                invoice_line_vals = []
                exchange_inv_line_vals = []
                for rma_line in rma.rma_picking_lines_ids:
                    state = 'approve'
                    rma_move_vals_b2b = {
                        'product_id': rma_line.product_id and
                        rma_line.product_id.id or False,
                        'name': rma_line.product_id and
                        rma_line.product_id.name or False,
                        'origin': rma.name,
                        'product_uom_qty': rma_line.refund_qty or 0,
                        'location_id': rma_line.source_location_id.id or False,
                        'location_dest_id':
                        rma_line.destination_location_id.id or
                        False,
                        'product_uom': rma_line.product_id.uom_id and
                        rma_line.product_id.uom_id.id or False,
                        'rma_id': rma.id,
                        'price_unit': rma_line.price_subtotal or 0,
                    }
                    stock_moves_vals.append((0, 0, rma_move_vals_b2b))
                    inv_account_id = rma_line.product_id. \
                        property_account_income_id and \
                        rma_line.product_id. \
                        property_account_income_id.id or \
                        rma_line.product_id.categ_id. \
                        property_account_income_categ_id and \
                        rma_line.product_id.categ_id. \
                        property_account_income_categ_id.id or False
                    if not inv_account_id:
                        raise ValidationError((
                            'No account defined for product "%s".') %
                            rma_line.product_id.name)
                    prod_price = 0.0
                    if rma_line.refund_qty != 0:
                        prod_price = float(
                            (rma_line.refund_price) / float(
                                rma_line.refund_qty))
                    inv_line_values = {
                        'product_id': rma_line.product_id and rma_line.
                        product_id.id or False,
                        'account_id': inv_account_id or False,
                        'name': rma_line.product_id and rma_line.
                        product_id.name or False,
                        'quantity': rma_line.refund_qty or 0,
                        'price_unit': prod_price or 0,
                        'currency_id': rma.currency_id.id or False,
                    }

                    if rma_line.tax_id and rma_line.tax_id.ids:
                        inv_line_values.update(
                            {'invoice_line_tax_ids': [(6, 0, rma_line.
                                                       tax_id.ids)]})

                    invoice_line_vals.append((0, 0, inv_line_values))

                    if rma_line.type == 'exchange':
                        state = 'approve'
                        rma_move_vals_b2c = {
                            'product_id': rma_line.exchange_product_id and
                            rma_line.exchange_product_id.id or False,
                            'name': rma_line.exchange_product_id and
                            rma_line.exchange_product_id.name or False,
                            'origin': rma.name,
                            'product_uom_qty': rma_line.refund_qty or 0,
                            'location_id':
                            rma_line.destination_location_id.id or
                            False,
                            'location_dest_id':
                            rma_line.source_location_id.id or
                            False,
                            'product_uom':
                            rma_line.exchange_product_id.uom_id and
                            rma_line.exchange_product_id.uom_id.id or False,
                            'rma_id': rma.id,
                            'price_unit': rma_line.price_subtotal or 0,
                        }
                        exchange_move_vals.append((0, 0, rma_move_vals_b2c))
                        inv_line_vals_exchange = {
                            'product_id': rma_line.exchange_product_id and
                            rma_line.exchange_product_id.id or False,
                            'account_id': inv_account_id or False,
                            'name': rma_line.exchange_product_id and rma_line.
                            exchange_product_id.name or False,
                            'quantity': rma_line.refund_qty or 0,
                            'price_unit':
                            rma_line.exchange_product_id.lst_price or 0,
                            'currency_id': rma.currency_id.id or False,
                        }
                        exchange_inv_line_vals.append(
                            (0, 0, inv_line_vals_exchange))

                        if rma_line.tax_id and rma_line.tax_id.ids:
                            inv_line_vals_exchange.update(
                                {'invoice_line_tax_ids': [(6, 0, rma_line.
                                                           tax_id.ids)]})

                            exchange_inv_line_vals.append(
                                (0, 0, inv_line_vals_exchange))
                for move in stock_moves_vals:
                    picking = self.env['stock.picking'].search([
                        ('rma_id', '=', rma.id),
                        ('location_id', '=', move[2]['location_id']),
                        ('location_dest_id', '=',
                         move[2]['location_dest_id'])])
                    if not picking:
                        picking_type_id = self.env[
                            'stock.picking.type'].search([
                                ('code', '=', 'incoming'),
                                ('warehouse_id.company_id', 'in',
                                 [self.env.context.get(
                                     'company_id',
                                     self.env.user.company_id.id),
                                  False])],
                            limit=1).id
                        picking_vals = {
                            'move_type': 'one',
                            'picking_type_id': picking_type_id or False,
                            'partner_id': rma.picking_partner_id and
                            rma.picking_partner_id.id or
                            rma.picking_rma_id.partner_id.id or
                            False,
                            'origin': rma.name,
                            'move_lines': [move],
                            'location_id': move[2]['location_id'],
                            'location_dest_id': move[2]['location_dest_id'],
                            'rma_id': rma.id,
                        }
                        picking_rec = self.env[
                            'stock.picking'].create(picking_vals)
                        picking_rec.action_confirm()
                        picking_rec.action_assign()

                    else:
                        move[2]['picking_id'] = picking.id
                        self.env['stock.move'].create(move[2])
                for vals in exchange_move_vals:
                    ex_picking = self.env['stock.picking'].search([
                        ('rma_id', '=', rma.id),
                        ('location_id', '=', vals[2]['location_id']),
                        ('location_dest_id', '=', vals[2]['location_dest_id']),
                        ('picking_type_code', '=', 'outgoing')])
                    if not ex_picking:
                        picking_type = self.env['stock.picking.type'].search([
                            ('code', '=', 'outgoing'),
                            ('warehouse_id.company_id', 'in',
                             [self.env.context.get('company_id',
                                                   self.env.user.company_id.id
                                                   ),
                              False])],
                            limit=1).id
                        exchange_picking_vals = {
                            'move_type': 'one',
                            'picking_type_id': picking_type or False,
                            'partner_id': rma.picking_partner_id and
                            rma.picking_partner_id.id or
                            rma.picking_rma_id.partner_id.id or
                            False,
                            'origin': rma.name,
                            'move_lines': [vals],
                            'location_id': vals[2]['location_id'],
                            'location_dest_id': vals[2]['location_dest_id'],
                            'rma_id': rma.id,
                        }
                        picking_rec_ex = self.env[
                            'stock.picking'].create(exchange_picking_vals)
                        picking_rec_ex.action_confirm()
                        picking_rec_ex.action_assign()
                    else:
                        vals[2]['picking_id'] = ex_picking.id
                        self.env['stock.move'].create(vals[2])
                if invoice_line_vals:
                    inv_values = {
                        'type': 'out_refund',
                        'origin': rma.name or '',
                        'name': rma.name or '',
                        'comment': rma.problem or '',
                        'partner_id': rma.picking_partner_id and
                        rma.picking_partner_id.id or
                        rma.picking_rma_id.partner_id.id or False,
                        'account_id': rma.picking_partner_id.
                        property_account_receivable_id and
                        rma.picking_partner_id.property_account_receivable_id.
                        id or
                        False,
                        'invoice_line_ids': invoice_line_vals,
                        'date_invoice': rma.rma_date or False,
                        'rma_id': rma.id,
                    }
                    self.env['account.invoice'].create(inv_values)

                if exchange_inv_line_vals:
                    ex_inv_vals = {
                        'type': 'out_invoice',
                        'comment': rma.problem or '',
                        'origin': rma.name or '',
                        'name': rma.name or '',
                        'partner_id': rma.picking_partner_id and
                        rma.picking_partner_id.id or
                        rma.picking_rma_id.partner_id.id or False,
                        'account_id':
                        rma_line.exchange_product_id.
                        property_account_expense_id and
                        rma_line.exchange_product_id.
                        property_account_expense_id.id or
                        False,
                        'invoice_line_ids': exchange_inv_line_vals,
                        'date_invoice': rma.rma_date or False,
                        'rma_id': rma.id,
                    }
                    self.env['account.invoice'].create(ex_inv_vals)
                rma.write({'state': state})
            return True

class RmaSaleLines(models.Model):
    _inherit = "rma.sale.lines"

    so_line_id = fields.Many2one('sale.order.line')


class RmaPurchaseLines(models.Model):
    _inherit = "rma.purchase.lines"

    po_line_id = fields.Many2one('purchase.order.line')