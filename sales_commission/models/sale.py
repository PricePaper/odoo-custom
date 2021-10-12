# -*- coding: utf-8 -*-

from odoo import models, fields, api
import csv


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sales_person_ids = fields.Many2many('res.partner', related="partner_id.sales_person_ids", string='Associated Sales Persons', readonly=True)

    # @api.multi
    # @api.onchange('partner_id')
    # def onchange_partner_id(self):
    #     res = super(SaleOrder, self).onchange_partner_id()
    #     if self.partner_id and self.partner_id.sales_person_ids:
    #         self.sales_person_ids = self.partner_id.sales_person_ids
    #     return res
    #
    # @api.multi
    # def _prepare_invoice(self):
    #     res = super(SaleOrder, self)._prepare_invoice()
    #     if self.sales_person_ids:
    #         res.update({
    #             'sales_person_ids': [(6, 0, self.sales_person_ids.ids)]
    #         })
    #     return res

    @api.model
    def correct_csb(self):
        csb_ids = []
        for aml in self.env['account.move.line'].search([('account_id', '=', 529), ('journal_id', '=', 8)]):
            a = 0
            b = self.env['account.batch.payment'].search([('name','=', aml.ref)])
            if aml.credit == sum(b.mapped('payment_ids').mapped('amount')):
                for p in b.payment_ids:
                    csb_aml = self.env['account.move.line'].search([('account_id', '=', 529), ('journal_id', '=', 14), ('credit', '=', p.amount), ('id', 'not in', csb_ids)])
                    csb_ids.extend(csb_aml.ids)
                    if csb_aml:
                        a+=p.amount
            if a == aml.credit:
                aml.mapped('move_id').button_cancel()
        return csb_ids



    @api.model
    def correct_sc_po(self):
        # pass
        # csvfile = open('scd_journal.csv', 'a+')
        # fs = ['sc', 'invoice', 'po', 'jrnl', 'name','note', 'accout','debit', 'credit']
        # writer = csv.DictWriter(csvfile, fieldnames=fs)
        # writer.writeheader()
        for sc in self.search([('storage_contract', '=', True)]): #self.browse(103269):#.search([('storage_contract', '=', True)]):
            #     res = {'sc':sc.name}        
            #     # writer.writerow({'sc':sc.name})
            #     stc = ch = 0
            for line in sc.order_line:
                if line.storage_contract_line_ids:
                    move = line.storage_contract_line_ids.mapped('move_ids').mapped('account_move_ids')
                    if 683 not in move.mapped('line_ids').mapped('account_id').ids:
                        aml = move.mapped('line_ids').filtered(lambda r: r.account_id.id == 687)
                        aml.mapped('move_id').button_cancel()
                        aml.write({'account_id': 683})
                        aml.mapped('move_id').post()
                if line.purchase_line_ids:
                    move = line.purchase_line_ids.mapped('move_ids').mapped('account_move_ids')
                    if 683 not in move.mapped('line_ids').mapped('account_id').ids:
                        aml = move.mapped('line_ids').filtered(lambda r: r.account_id.id == 687)
                        aml.mapped('move_id').button_cancel()
                        aml.write({'account_id': 683})
                        aml.mapped('move_id').post()
        return True
        #             move = sc_line.storage_contract_line_ids.mapped('move_ids').mapped('account_move_ids')
        #             for line in move.mapped('line_ids'):
        #                 # print(line.account_id.id)
        #                 if line.account_id.id == 683:
        #                     # print(ch, line.account_id.id, line.credit , line.debit )
        #                     ch += line.credit or line.debit                 
        #                 writer.writerow({'sc':sc.name, 'jrnl':line.move_id.name, 'name': line.name, 'note': 'sc child stock journal_id', 'accout': line.account_id.display_name, 'debit': line.debit, 'credit':line.credit})
        #             inv = sc_line.storage_contract_line_ids.mapped('invoice_lines.invoice_id')                    
        #             for i in inv:
        #                 for line in i.move_id.line_ids:  

        #                     writer.writerow({'sc':sc.name, 'invoice': i.number,'jrnl':line.move_id.name, 'name': line.name, 'note': 'sc child  invoice journal_id', 'accout': line.account_id.display_name, 'debit': line.debit, 'credit':line.credit})
        #         if sc_line.purchase_line_ids:
        #             move = sc_line.purchase_line_ids.mapped('move_ids').mapped('account_move_ids')
        #             for line in move.mapped('line_ids'):
        #                 if line.account_id.id == 683:
        #                     stc += line.credit or line.debit
        #                 writer.writerow({'sc':sc.name, 'po': sc_line.purchase_line_ids.mapped('order_id.name'),'jrnl':line.move_id.name, 'name': line.name, 'note': 'sc  stock journal_id', 'accout': line.account_id.display_name, 'debit': line.debit, 'credit':line.credit})
        #         if sc_line.invoice_lines:
        #             inv = sc_line.invoice_lines.mapped('invoice_id')
        #             for i in inv:
        #                 for line in i.move_id.line_ids:
        #                     writer.writerow({'sc':sc.name, 'invoice': i.number,'jrnl':line.move_id.name, 'name': line.name, 'note': 'sc invoice journal_id', 'accout': line.account_id.display_name, 'debit': line.debit, 'credit':line.credit})

        #     print(sc.name, stc, ch)
        # csvfile.close()
        #             move = line.storage_contract_line_ids.mapped('move_ids').mapped('account_move_ids')
        #             if 683 not in move.mapped('line_ids').mapped('account_id').ids:
        #                 aml = move.mapped('line_ids').filtered(lambda r: r.account_id.id == 687)
        #                 aml.mapped('move_id').button_cancel()
        #                 aml.write({'account_id': 683})
        #                 aml.mapped('move_id').post()
        #         if line.purchase_line_ids:
        #             move = line.purchase_line_ids.mapped('move_ids').mapped('account_move_ids')
        #             if 683 not in move.mapped('line_ids').mapped('account_id').ids:
        #                 aml = move.mapped('line_ids').filtered(lambda r: r.account_id.id == 687)
        #                 aml.mapped('move_id').button_cancel()
        #                 aml.write({'account_id': 683})
        #                 aml.mapped('move_id').post()
        # return False

    @api.model
    def link_sc(self, sc_line_id=False, po_line_id=False):
        sc_line = self.env['sale.order.line'].browse(sc_line_id)
        po_line = self.env['purchase.order.line'].browse(po_line_id)
        po_line.write({'sale_line_id': sc_line.id})
        po_line.move_ids.write({'sale_line_id': sc_line.id, 'is_storage_contract': True})
        po_line.invoice_lines.write({'is_storage_contract': True})
        sc_line.order_id.write({'state': 'released', 'sc_po_done': True})
        return True

    @api.model
    def correct_sc(self, order_ids=[]):
        if not order_ids:
            return
        sc_inv = 0        
        for order in self.browse(order_ids):
            line_ids = []
            order.action_storage_contract_confirm()
            for line in order.order_line:
                if line.product_uom_qty > line.product_id.qty_available:
                    line.product_uom_qty = line.product_id.qty_available
                sc_inv = line.product_uom_qty * line.product_id.standard_price
                line_ids.extend([[0,0, {                                
                                'debit': sc_inv,
                                'credit': 0,
                                'journal_id': 3,
                                'name': "Storage contract inventory transfer %s" % line.product_id.name,                                
                                'account_id': 683,
                                'date_maturity': "2021-4-30",
                            }],
                            [0,0, {                                
                                'debit': 0,
                                'credit': sc_inv,
                                'journal_id': 3,
                                'name': "Storage contract inventory transfer %s" % line.product_id.name,
                                'account_id': 687,
                                'date_maturity': "2021-4-30",
                            }],[0,0, {                                
                                'debit': 0,
                                'credit': sc_inv,
                                'journal_id': 3,
                                'name': "Storage contract cost transfer %s" % line.product_id.name,
                                'account_id': 769,
                                'date_maturity': "2021-4-30",
                            }],[0,0, {                                
                                'debit': sc_inv,
                                'credit': 0,
                                'journal_id': 3,
                                'name': "Storage contract cost transfer %s" % line.product_id.name,
                                'account_id': 29,
                                'date_maturity': "2021-4-30",
                            }],])        
            move_id = self.env['account.move'].create({
                'ref': "Storage contract imported order %s transfer" % order.name,
                'line_ids': line_ids,
                'journal_id': 3,
                'date': "2021-4-30",
                'narration': "Storage contract imported orders transfer",
            })
            move_id.post()
            order.action_release()
        return True

SaleOrder()

class SaleOrder_line(models.Model):
    _inherit = 'sale.order.line'

    sales_person_ids = fields.Many2many('res.partner',  compute='get_sales_persons', string='Associated Sales Persons', search='search_sales_persons')


    @api.depends('order_id.partner_id', 'order_partner_id', 'order_partner_id.sales_person_ids')
    def get_sales_persons(self):
        for rec in self:
            rec.sales_person_ids = [(6, 0, rec.order_partner_id.sales_person_ids.ids)]


    @api.multi
    def search_sales_persons(self, operator, value):
        commission = self.env['commission.percentage'].search([('sale_person_id', operator, value)])
        partner = commission.mapped('partner_id')
        order = self.env['sale.order']._search([('partner_id', 'in', partner.ids)])
        return[('order_id', 'in', order)]

    

SaleOrder_line()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
