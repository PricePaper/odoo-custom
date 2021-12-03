from odoo import fields, models, api


class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    def action_batch_reconcile(self):
        for record in self:
            if all(payment.state == 'reconciled' for payment in record.payment_ids):
                record.state = 'reconciled'
