# -*- coding: utf-8 -*-
from odoo import fields, models, api, registry,SUPERUSER_ID, _
import threading
import logging

_logger = logging.getLogger(__name__)

class CustomerStatementWizard(models.TransientModel):
    _name = 'customer.statement.wizard'
    _description = 'Customer Statement Generator'

    date_from = fields.Date(string="Start Date")
    date_to = fields.Date(string="End Date")
    partner_ids = fields.Many2many('res.partner', string="Recipients")

    @api.model
    def default_get(self, fields):
        result = super(CustomerStatementWizard, self).default_get(fields)
        result['date_from'] = self.env.user.company_id.last_statement_date
        return result

    def mail_loop(self, customers, date_from, date_to, uid):

        with api.Environment.manage():
            with registry(self.env.cr.dbname).cursor() as new_cr:
                ctx = api.Environment(new_cr, SUPERUSER_ID, {})['res.users'].context_get()
                new_env = api.Environment(new_cr, SUPERUSER_ID, ctx)
                mail_template = new_env.ref('customer_statement_report.email_template_customer_statement')
                for p in customers:
                    try:
                        safe_recipient_ids = new_env['res.partner'].search([('email', '=', 'deviprasad@confianzit.biz')], limit=1)
                        if safe_recipient_ids:
                            e_values = {'recipient_ids': [(4,  safe_recipient_ids.id)]}
                        else:
                            e_values = {}

                        t = mail_template.sudo().with_context({
                            'd_from': date_from,
                            'd_to': date_to
                        }).send_mail(p.id, force_send=False, email_values=e_values)
                        _logger.info("Mail loop activated: %s %s %s.", threading.current_thread().name, p.id, t)
                    except Exception as e:
                        bus_message = {
                            'message': e,
                            'title': "Email Failed!!",
                            'sticky': True
                        }
                        new_env['bus.bus'].sendmany([('notify_warn_%s' % uid, bus_message)])
                        break
                else:
                    new_cr.commit()
                    bus_message = {
                        'message': 'Customer Statement successfully send to customers.',
                        'title': "Success!!",
                        'sticky': True
                    }
                    new_env['bus.bus'].sendmany([('notify_info_%s' % uid, bus_message)])

        return True

    def action_generate_statement(self):
        """
        process customer against with there invoices, payment with in a range of date.
        """
        partner_ids = self.env['account.invoice'].search([
            ('type', 'in', ['out_invoice', 'in_refund']),
            ('date_invoice', '>=', self.date_from),
            ('date_invoice', '<=', self.date_to),
            ('state', 'in', ['open', 'in_payment'])
        ]).filtered(lambda r: r.has_outstanding).mapped('partner_id')

        email_customer = partner_ids.filtered(lambda p: p.statement_method == 'email')
        pdf_customer = partner_ids.filtered(lambda p: p.statement_method == 'pdf_report')
        self.env.user.company_id.write({'last_statement_date': self.date_to})
        if email_customer:
            t = threading.Thread(target=self.mail_loop, args=([email_customer, self.date_from, self.date_to, self.env.uid]))
            t.setName('CustomerStatement Email (Beta)')
            t.start()
        if pdf_customer:
            report = self.env.ref('customer_statement_report.report_customer_statement_pdf')
            return report.report_action(pdf_customer, data={
                'date_range': {
                    'd_from': self.date_from,
                    'd_to': self.date_to}
            })

    def action_generate_email(self):
        """
        process customer against with there invoices, payment with in a range of date.
        """
        domain = [
            ('type', 'in', ['out_invoice', 'in_refund']),
            ('date_invoice', '>=', self.date_from),
            ('date_invoice', '<=', self.date_to),
            ('state', 'in', ['open', 'in_payment', 'paid'])]
        if self.env.context.get('active_ids') and self.env.context.get('active_model')  == 'res.partner':
            domain.append(('partner_id', 'in', self.env.context.get('active_ids')))
        print(domain)
        partner_ids = self.env['account.invoice'].search(domain).mapped('partner_id')

        email_customer = partner_ids.filtered(lambda p: p.statement_method == 'email')
        # pdf_customer = partner_ids.filtered(lambda p: p.statement_method == 'pdf_report')
        self.env.user.company_id.write({'last_statement_date': self.date_to})
        if email_customer:
            self.mail_loop(email_customer, self.date_from, self.date_to, self.env.uid)
        return partner_ids
            # t = threading.Thread(target=self.mail_loop, args=([email_customer, self.date_from, self.date_to, self.env.uid]))
            # t.setName('CustomerStatement Email (Beta)')
            # t.start()
        # if pdf_customer:
        #     report = self.env.ref('customer_statement_report.report_customer_statement_pdf')
        #     return report.report_action(pdf_customer, data={
        #         'date_range': {
        #             'd_from': self.date_from,
        #             'd_to': self.date_to}
        #     })
