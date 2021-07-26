# -*- coding: utf-8 -*-

from odoo import models, fields, api


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    batch_id = fields.Many2one('stock.picking.batch', string='Delivery Batch')
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted'), ('sent', 'Sent'), ('reconciled', 'Reconciled'),
                              ('cancelled', 'Cancelled')], readonly=True, default='draft', copy=False, string="Status", track_visibility='onchange')
    common_batch_id = fields.Many2one('batch.payment.common', string='Delivery Batch')

    @api.multi
    def print_checks(self):
        self.set_check_amount_in_words()
        self.state
        return super(AccountPayment, self).print_checks()


AccountPayment()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
