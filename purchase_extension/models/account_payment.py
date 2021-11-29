from odoo import fields, models, api


class AccountPayment(models.Model):
    _inherit = "account.payment"

    discount_hold = fields.Boolean(string="Discount Hold", default=False)

    @api.multi
    def post(self):
        for rec in self:
            if rec.discount_hold:
                for line in rec.payment_lines:
                    discount_journal = line.discount_journal_id
                    invoice = line.invoice_id
                    if discount_journal and invoice and invoice.state != 'paid':
                        rcv_lines = invoice.move_id.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
                        rcv_wrtf = discount_journal.line_ids.filtered(lambda r: r.account_id.user_type_id.type in ('receivable', 'payable'))
                        (rcv_lines + rcv_wrtf).reconcile()
                        rec.write({'discount_hold': False})
        res = super(AccountPayment, self).post()
        return res
