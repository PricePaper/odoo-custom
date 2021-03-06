# -*- encoding: utf-8 -*-

from datetime import datetime, timedelta

from odoo import api, fields, models


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    @api.model
    def _cron_purge_old_open_credits(self):
        limit_days = self.env.user.company_id and self.env.user.company_id.purge_old_open_credit_limit or 120
        domain_date = datetime.today() - timedelta(days=limit_days)
        credit_notes = self.search([
            ('state', '=', 'open'),
            ('type', '=', 'out_refund'),
            ('date_invoice', '<', domain_date.strftime('%Y-%m-%d')),
        ]).sudo()
        credit_notes.action_invoice_cancel()
        return True


AccountInvoice()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
