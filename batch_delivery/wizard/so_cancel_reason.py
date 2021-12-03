# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class CostChangePercentage(models.TransientModel):
    _name = 'so.cancel.reason'
    _description = "SO cancel reason"

    reason = fields.Text(string='Reason')

    @api.multi
    def cancel_so(self):
        """
        Cancel SO and add the reason to it
        """

        active_id = self._context.get('active_id')
        order = self.env['sale.order'].browse(active_id)
        reason = self.reason
        if order.cancel_reason:
            reason = order.cancel_reason + '\n' + self.reason
        order.cancel_reason = reason
        order.with_context(from_cancel_wizard=True).action_cancel()




CostChangePercentage()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
