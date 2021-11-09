# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

import json
import io
from odoo.tools import date_utils

from itertools import groupby

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter


class CostDiscrepancyReport(models.TransientModel):
    _name = 'cost.discrepancy.report'
    _description = 'cost - price discrepancy between product and po line'

    start_date = fields.Datetime(string='Start Date')
    end_date = fields.Datetime(string='End Date')

    def generate_data(self, start_date, end_date):
        """Custom generator for grouping data for excel report."""
        po_lines = self.env['purchase.order.line'].search([
            ('state', 'in', ['purchase', 'done', 'received']),
            ('date_order', '>=', start_date),
            ('date_order', '<=', end_date)
        ])

        if not po_lines:
            raise UserError(_('Nothing to print.'))

        for xls_group_key, xls_lines in groupby(po_lines.sorted(
                    key=lambda sort_key: sort_key.product_id.id
                ), key=lambda group_key: (group_key.product_id, group_key.order_id.user_id)):
            for line in xls_lines:
                if line.price_unit - xls_group_key[0].standard_price:
                    yield xls_group_key, line

    @api.multi
    def print_xlxs(self):
        data = {'start_date': self.start_date, 'end_date': self.end_date}
        return {
            'type': 'ir_actions_xlsx_download',
            'data': {'model': 'cost.discrepancy.report',
                     'options': json.dumps(data, default=date_utils.json_default),
                     'output_format': 'xlsx',
                     'report_name': 'Discrepancy Report %s 🠚 %s' % (self.start_date, self.end_date)
                     },
            'report_type': 'xlsx',
        }

    def get_xlsx_report(self, data, response):
        # Create a workbook and add a worksheet.
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet()
        cell_format = workbook.add_format({'font_size': '10px'})
        head = workbook.add_format({'align': 'center', 'bold': True, 'font_size': '13px'})

        # Add a bold format to use to highlight cells.
        sheet.set_column('A:A', 15)
        sheet.set_column('B:B', 32)
        sheet.set_column('C:C', 15)
        sheet.set_column('D:D', 15)
        sheet.set_column('E:E', 15)
        sheet.set_column('F:F', 15)

        sheet.write(0, 0, 'Product Code', head)
        sheet.write(0, 1, 'Product Name', head)
        sheet.write(0, 2, 'Purchase User', head)
        sheet.write(0, 3, 'Price Unit', head)
        sheet.write(0, 4, 'Standard Price', head)
        sheet.write(0, 5, 'Discrepancy', head)

        row, col = 1, 0
        for group_key, line in self.generate_data(data['start_date'], data['end_date']):
            sheet.write(row, 0, group_key[0].default_code, cell_format)
            sheet.write(row, 1, group_key[0].name, cell_format)
            sheet.write(row, 2, group_key[1].name, cell_format)
            sheet.write(row, 3, line.price_unit, cell_format)
            sheet.write(row, 4, group_key[0].standard_price, cell_format)
            sheet.write(row, 5, round(line.price_unit - group_key[0].standard_price, 2), cell_format)
            row += 1
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
