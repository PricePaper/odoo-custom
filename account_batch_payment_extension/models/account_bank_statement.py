# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    is_return_cleared = fields.Boolean('Return cleared')

    def process_reconciliation(self, counterpart_aml_dicts=None, payment_aml_rec=None, new_aml_dicts=None):

        counterpart_moves = super().process_reconciliation(counterpart_aml_dicts=counterpart_aml_dicts, payment_aml_rec=payment_aml_rec, new_aml_dicts=new_aml_dicts)
        statement_line = counterpart_moves.mapped('line_ids').mapped('statement_line_id')
        if len(payment_aml_rec.mapped('journal_id')) == 1 and payment_aml_rec.mapped('journal_id').id != self.journal_id.id and payment_aml_rec.mapped('journal_id').type  == 'cash':
            for aml in payment_aml_rec:
                if aml.journal_id.type == 'cash' and aml.debit > 0:
                    journal = self.env.ref('account_batch_payment_extension.account_journal_cash_to_bank')
                    if not journal:
                        raise UserError("Journal \"Cash to Bank\" is not configured")
                    move_vals = {
                        'date': self.date,
                        'ref': 'Cash transfer to bank',
                        'company_id': self.company_id.id,
                        'journal_id': journal.id,
                        'line_ids': [[0, 0, {
                            'partner_id': self.partner_id.id or False,
                            # 'move_id': move_id,
                            'debit': 0,
                            'credit': aml.debit,
                            'journal_id': journal.id,
                            'account_id': aml.account_id.id
                            }],
                            [0,0,{
                            'partner_id': self.partner_id.id or False,
                            # 'move_id': move_id,
                            'debit': aml.debit,
                            'credit': 0,
                            'journal_id': journal.id,
                            'account_id': journal.default_debit_account_id.id
                            }]]
                    }
                    self.env['account.move'].create(move_vals).post()
        for stmt in statement_line:
            if 'DEPOSITED ITEM RETURNED' in stmt.name:
                cheque_no = stmt.name and stmt.name.split('CK#:')
                if cheque_no and len(cheque_no) > 1:
                    cheque_no = cheque_no[1].split(' ', 1)[0]
                    cheque_no_strip = cheque_no.lstrip('0')
                    payment = self.env['account.payment'].search(['|', ('communication', '=', cheque_no_strip), ('communication', '=', cheque_no)])
                    vals = {'bank_stmt_line_id': stmt.id}
                    if payment:
                        vals['payment_ids'] = [(6, 0, payment.ids)]
                        vals['partner_ids'] = [(6, 0, payment.mapped('partner_id').ids)]
                    if not payment and stmt.partner_id:
                        vals['partner_ids'] = [(6, 0, stmt.mapped('partner_id').ids)]
                    self.env['process.returned.check'].create(vals)
        return counterpart_moves

    @api.multi
    def button_cancel_reconciliation(self):
        for st_line in self:
            if 'DEPOSITED ITEM RETURNED' in st_line.name:
                process_check = self.env['process.returned.check'].search([('bank_stmt_line_id', '=', st_line.id), ('state', '!=', 'cancel')])
                if len(process_check) > 1:
                    raise UserError("There is more than one record in the process rerturn check")
                elif process_check:
                    process_check.undo_process()

        return super(AccountBankStatementLine, self).button_cancel_reconciliation()

AccountBankStatementLine()



class AccountReconcileModel(models.Model):
    _inherit = 'account.reconcile.model'

    @api.multi
    def _apply_rules(self, st_lines, excluded_ids=None, partner_map=None):
        res = super()._apply_rules(st_lines, excluded_ids, partner_map)
        batch_payemnt = {'inbound': self.env['account.batch.payment'], 'outbound': self.env['account.batch.payment']}
        re = self.env['account.account'].search(
            [('user_type_id', '=', self.env.ref('account.data_account_type_receivable').id)], limit=1)

        for p in self.env['account.batch.payment'].search([('state', '=', 'sent')]):
            if p.batch_type == 'inbound':
                batch_payemnt['inbound'] |= p
            else:
                batch_payemnt['outbound'] |= p
        for line in st_lines:
            line_residual = line.currency_id and line.amount_currency or line.amount
            if line_residual > 0:
                batch = batch_payemnt['inbound'].filtered(lambda rec: rec.amount == abs(line_residual))
                if batch:
                    journal_accounts = [
                            batch.journal_id.default_debit_account_id.id,
                            batch.journal_id.default_credit_account_id.id
                        ]
                    for aml in batch.mapped('payment_ids').mapped('move_line_ids').filtered(lambda r: r.account_id.id in journal_accounts):
                        if aml.debit:
                            res.get(line.id, {}).get('aml_ids', []).append(aml.id)
            else:
                batch = batch_payemnt['outbound'].filtered(lambda rec: rec.amount == abs(line_residual))
                if batch:
                    journal_accounts = [
                            batch.journal_id.default_debit_account_id.id,
                            batch.journal_id.default_credit_account_id.id
                        ]
                    for aml in batch.mapped('payment_ids').mapped('move_line_ids').filtered(lambda r: r.account_id.id in journal_accounts):
                        if aml.credit:
                            res.get(line.id, {}).get('aml_ids', []).append(aml.id)
            if len(res.get(line.id, {}).get('aml_ids')) < 1 and line_residual < 0 and 'CHECK #' in line.name:
                memo = line.name.split('CHECK #', 1)
                domain = [('state', 'in', ('posted', 'sent')),('payment_type', '=', 'outbound'), ('amount', '=', abs(line_residual))]
                if len(memo) > 1:
                    memo = memo[1].strip().split(' ', 1)[0]
                    domain = [('state', 'in', ('posted', 'sent')),('payment_type', '=', 'outbound'), \
                    '|', '|', ('communication', '=', memo), ('check_number', '=', memo), ('amount', '=', abs(line_residual))]
                payment = self.env['account.payment'].search(domain)
                if payment:
                    if len(payment) > 1:
                        journal = payment[0].journal_id
                    else:
                        journal = payment.journal_id
                    journal_accounts = [
                                journal.default_debit_account_id.id,
                                journal.default_credit_account_id.id
                            ]
                    aml = payment.mapped('move_line_ids').filtered(lambda r: r.account_id.id in journal_accounts and r.credit)
                    res.get(line.id, {}).get('aml_ids', []).extend(aml.ids)
        return res



AccountReconcileModel()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
