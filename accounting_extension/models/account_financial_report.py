from odoo import fields, models, api


class ReportAccountFinancialReport(models.Model):
    _inherit = "account.financial.html.report"

    def _get_columns_name(self, options):
        columns = super(ReportAccountFinancialReport, self)._get_columns_name(options)
        if columns and options.get('journals', []):
            columns += [{'name': '%', 'class': 'number'}]
        return columns

    @api.multi
    def _get_lines(self, options, line_id=None):
        line_obj = self.line_ids
        if line_id:
            line_obj = self.env['account.financial.html.report.line'].search([('id', '=', line_id)])
        if options.get('comparison') and options.get('comparison').get('periods'):
            line_obj = line_obj.with_context(periods=options['comparison']['periods'])
        if options.get('ir_filters'):
            line_obj = line_obj.with_context(periods=options.get('ir_filters'))

        currency_table = self._get_currency_table()
        domain, group_by = self._get_filter_info(options)

        if group_by:
            options['groups'] = {}
            options['groups']['fields'] = group_by
            options['groups']['ids'] = self._get_groups(domain, group_by)

        amount_of_periods = len((options.get('comparison') or {}).get('periods') or []) + 1
        amount_of_group_ids = len(options.get('groups', {}).get('ids') or []) or 1
        linesDicts = [[{} for _ in range(0, amount_of_group_ids)] for _ in range(0, amount_of_periods)]

        res = line_obj.with_context(
            cash_basis=options.get('cash_basis'),
            filter_domain=domain,
        )._get_lines(self, currency_table, options, linesDicts)

        dummy = options.copy()
        dummy.update(unfold_all=False, unfolded_lines=[])
        out = self.line_ids.with_context(
            cash_basis=options.get('cash_basis'),
            filter_domain=domain,
        )._get_lines(self, currency_table, dummy, linesDicts)

        income = list(filter(lambda r: r['name'] == 'Operating Income' or r['id'] == 5, out))

        if income:
            t = income[0]['columns'][0].get('no_format_name') or income[0]['columns'][0].get('name')
            for l in res:
                if l.get('caret_options') or l.get('id') == 'total_6' or l.get('name') == 'Total Gross Profit' or l.get('id') == 4 and l.get('class') == 'total':
                    s = l['columns'][0].get('no_format_name') or l['columns'][0].get('name')
                    p = (s / t) * 100
                    l['columns'].append({
                        'name': '{0:0.2f}%'.format(p),
                        'no_format_name': p,
                        'class': 'number'
                    })
        return res


ReportAccountFinancialReport()
