# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import datetime

class CostChangePercentage(models.TransientModel):
    _name = 'prophet.forecast.days'
    _description = "FB prophet forecast days"

    number_of_days = fields.Integer(string='# of days', default=30)

    @api.multi
    def show_forecast(self):
        """
        Show forecast
        """

        active_id = self._context.get('active_id')
        product = self.env['product.product'].browse(active_id)
        forecast, to_date = product.show_forecast(no_of_days=self.number_of_days)


        self.env['product.forecast'].search([]).unlink()
        flag = False
        count = 0
        for ele in forecast:
            if datetime.datetime.strptime(ele[0], '%Y-%m-%d').date() >= to_date:
                flag = True
            if flag:
                count += 1
                self.env['product.forecast'].create({
                    'product_id': self.id,
                    'date': ele[0],
                    'quantity': ele[1],  # quantity,
                    'quantity_min': ele[2],  # min_quantity,
                    'quantity_max': ele[3],  # max_quantity,
                })

        graph_id = self.env.ref('stock_orderpoint_enhancements.view_order_product_forecast_graph').id
        pivot_id = self.env.ref('stock_orderpoint_enhancements.view_order_product_forecast_pivot').id
        res = {
            "type": "ir.actions.act_window",
            "name": "Sale Forecast",
            "res_model": "product.forecast",
            "views": [[graph_id, "graph"], [pivot_id, "pivot"]],
            "domain": [["product_id", "=", self.id]],
            "target": "current",
        }
        print(res)
        return res




CostChangePercentage()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
