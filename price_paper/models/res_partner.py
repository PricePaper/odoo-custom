# -*- coding: utf-8 -*-

from lxml import etree

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.osv.orm import setup_modifiers


class ResPartner(models.Model):
    _inherit = 'res.partner'

    destination_code = fields.Char(string='Destination Code')
    corp_name = fields.Char(string='Corporate name ')
    fax_number = fields.Char(string='Fax')
    customer_pricelist_ids = fields.One2many('customer.pricelist', 'partner_id', string="Customer Pricelists")
    customer_code = fields.Char(string='Partner Code', copy=False)
    # comment the below line while running customer scripts
    established_date = fields.Date(string='Established Date', compute='_compute_estbl_date', store=True)
    # Uncomment the below line while running customer import scripts
    # established_date = fields.Date(string='Established Date')
    last_sold_date = fields.Date(string='Last Sold Date', compute='_compute_last_date', store=False)
    last_paid_date = fields.Date(string='Last Paid Date', compute='_compute_last_date', store=False)
    delivery_day_mon = fields.Boolean(string='Monday')
    delivery_day_tue = fields.Boolean(string='Tuesday')
    delivery_day_wed = fields.Boolean(string='Wednesday')
    delivery_day_thu = fields.Boolean(string='Thursday')
    delivery_day_fri = fields.Boolean(string='Friday')
    delivery_day_sat = fields.Boolean(string='Saturday')
    delivery_day_sun = fields.Boolean(string='Sunday')
    shipping_easiness = fields.Selection([('easy', 'Easy'), ('neutral', 'Neutral'), ('hard', 'Hard')],
                                         string='Easiness of shipping')
    change_delivery_days = fields.Boolean(string='Change Zip delivery days')
    zip_delivery_id = fields.Many2one('zip.delivery.day', string='Zip Delivery Days', compute='compute_delivery_day_id')
    zip_delivery_day_mon = fields.Boolean(string='Monday.', related='zip_delivery_id.delivery_day_mon')
    zip_delivery_day_tue = fields.Boolean(string='Tuesday.', related='zip_delivery_id.delivery_day_tue')
    zip_delivery_day_wed = fields.Boolean(string='Wednesday.', related='zip_delivery_id.delivery_day_wed')
    zip_delivery_day_thu = fields.Boolean(string='Thursday.', related='zip_delivery_id.delivery_day_thu')
    zip_delivery_day_fri = fields.Boolean(string='Friday.', related='zip_delivery_id.delivery_day_fri')
    zip_delivery_day_sat = fields.Boolean(string='Saturday.', related='zip_delivery_id.delivery_day_sat')
    zip_delivery_day_sun = fields.Boolean(string='Sunday.', related='zip_delivery_id.delivery_day_sun')
    zip_shipping_easiness = fields.Selection(related='zip_delivery_id.shipping_easiness',
                                             string='Easiness of shipping.')
    seller_info_ids = fields.One2many('product.supplierinfo', 'name', string='Seller info')
    seller_partner_ids = fields.Many2many('res.partner', 'vendor_id', 'seller_partner_id', string='Purchaser', domain="[('user_ids', '!=', False)]")
    credit_limit = fields.Float(string='Credit Limit', default=lambda self: self.env.user.company_id.credit_limit)
    default_shipping = fields.Boolean(string='Default', help="if checked this will be the default shipping address")
    property_account_payable_id = fields.Many2one('account.account', company_dependent=True,
        string="Account Payable", oldname="property_account_payable",
        domain="[('internal_type', '=', 'payable'), ('deprecated', '=', False)]",
        help="This account will be used instead of the default one as the payable account for the current partner",
        required=False)

    @api.depends('sale_order_ids.confirmation_date', 'invoice_ids.payment_ids.payment_date')
    def _compute_last_date(self):
        for rec in self:
            if rec.invoice_ids:
                payment_date_list = [payment.payment_date for payment in rec.invoice_ids.mapped('payment_ids') if
                                     payment.payment_date]
                payment_date = max(payment_date_list) if payment_date_list else False
                rec.last_paid_date = payment_date
            if rec.sale_order_ids:
                sale_date_list = [sale.confirmation_date.date() for sale in rec.sale_order_ids if
                                  sale.confirmation_date]
                sale_date = max(sale_date_list) if sale_date_list else False
                rec.last_sold_date = sale_date
                rec.established_date = min(sale_date_list) if sale_date_list else False

    def xmlrpc_compute_estbl_date(self):
        for rec in self:
            rec._compute_estbl_date()
        return True

    @api.depends('sale_order_ids.confirmation_date')
    def _compute_estbl_date(self):
        for rec in self:
            if rec.sale_order_ids and not rec.established_date:
                sale_date_list = [sale.confirmation_date.date() for sale in rec.sale_order_ids if
                                  sale.confirmation_date]
                sale_date = max(sale_date_list) if sale_date_list else False
                rec.established_date = min(sale_date_list) if sale_date_list else False

    @api.depends('zip')
    def compute_delivery_day_id(self):
        for rec in self:
            if rec.zip:
                zip_delivery_id = self.env['zip.delivery.day'].search([('zip', '=', rec.zip)])
                rec.zip_delivery_id = zip_delivery_id and zip_delivery_id.id or False
            else:
                rec.zip_delivery_id = False

    @api.model
    def default_get(self, fields_list):
        res = super(ResPartner, self).default_get(fields_list)
        res.update({
            'lastname': self._context.get('lastname'),
            'firstname': self._context.get('firstname')
        })
        if self.env.user.company_id:
            company = self.env.user.company_id
            res.update({
                'property_payment_term_id': self.env['account.payment.term'].search([('set_to_default', '=', True)], limit=1).id,
                'property_delivery_carrier_id': company.partner_delivery_method_id and company.partner_delivery_method_id.id or False,
                'country_id': company.partner_country_id and company.partner_country_id.id or False,
                'state_id': company.partner_state_id and company.partner_state_id.id or False})
        return res

    @api.model
    def fields_view_get(self, view_id=None, view_type=False, toolbar=False, submenu=False):
        res = super(ResPartner, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self.env.user._is_admin() and self.user_has_groups('base.group_no_one'):
            doc = etree.XML(res['arch'])
            if view_type == 'form':
                nodes = doc.xpath("//notebook/page[@name='sales_purchases']/group/group/field[@name='customer_code']")
                for node in nodes:
                    node.set('readonly', '0')
                    setup_modifiers(node, res['fields']['customer_code'])
                    res['arch'] = etree.tostring(doc)
                return res
        return res

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """
        overriden to display the search result
        based on customer code as well
        """
        res = super(ResPartner, self).name_search(name=name, args=args, operator=operator, limit=limit)
        if name:
            domain = [('customer_code', 'ilike', name)]
            if self._context.get('search_default_supplier', False):
                domain.append(('supplier', '=', True))
            elif self._context.get('search_default_customer', False):
                domain.append(('customer', '=', True))
            elif self._context.get('search_default_salesperson', False):
                domain.append(('is_sales_person', '=', True))
            if args:
                domain = domain + args
            customer_code_results = self.search(domain)
            customer_code_results = customer_code_results.name_get()
            for code in customer_code_results:
                if code[0] not in [rec[0] for rec in res]:
                    res.append(code)
        return res

    @api.multi
    def name_get(self):
        res = super(ResPartner, self).name_get()
        result=[]
        for partner in res:
            name = partner[1] or ''
            partner_id = self.env['res.partner'].browse(partner[0])
            if partner_id.customer_code and partner_id.customer and partner_id.type in('invoice','contact') and not partner_id.user_ids:
                name = '['+partner_id.customer_code+']'+name
            result.append((partner[0], name))
        return result



    @api.constrains('customer_code')
    def check_partner_code(self):
        if self.sudo().search(['|', ('active', '=', True), ('active', '=', False), ('customer_code', '=ilike', self.customer_code), ('id', '!=', self.id)]):
            raise ValidationError(_('Partner with same Partner code already exists.'))

    @api.model
    def create(self, vals):
        """
        Customer_code generation
        Pricelist creation
        if shiiping address is created as default uncheck
        the previous default shipping address (if exists)
        """

        if vals.get('is_company', False):
            if not vals.get('customer_code', False):
                prefix = vals.get('name').replace(" ", "")[0:3].upper()
                customer_codes = self.env['res.partner'].sudo().search(['|', ('active', '=', True), ('active', '=', False), ('customer_code', 'ilike', prefix)]).mapped('customer_code')
                partner_codes = [code for code in customer_codes if code[0:3] == prefix and len(code) < 8]
                count = 1
                while True:
                    suffix = str(count).zfill(3)
                    customer_code = prefix+suffix
                    if customer_code not in customer_codes:
                        vals['customer_code'] = customer_code
                        break
                    count+=1
        elif vals.get('parent_id', False):
            if not vals.get('customer_code', False) and vals.get('parent_id', False):
                parent = self.env['res.partner'].browse(vals.get('parent_id', False))
                child_codes = parent.child_ids.mapped('customer_code')
                count = 1
                while parent:
                    suffix = str(count).zfill(3)
                    customer_code = parent.customer_code + '-' + suffix
                    if customer_code not in child_codes:
                        vals['customer_code'] = customer_code
                        break
                    count+=1
        result = super(ResPartner, self).create(vals)
        if result.customer and result.is_company:
            result.setup_pricelist_for_new_customer()
        if result.parent_id and result.default_shipping:
            existing_defaults = self.search([('parent_id','=',result.parent_id.id),('type','=',result.type),('id','!=',result.id),('default_shipping','=', True)])
            if existing_defaults:
                existing_defaults.write({'default_shipping':False})
                result.default_shipping = True
        return result



    @api.multi
    def write(self, vals):
        # if 'property_payment_term_id' in vals and not self.env.user.has_group('account.group_account_invoice'):
        #     raise UserError("You dont have the rights to change the payment terms of this customer.")
        if 'seller_partner_ids' in vals:
            seller = self.browse(vals.get('seller_partner_ids')[0][-1])
            for rec in self:
                removel_ids = rec.seller_partner_ids - seller
                rec.seller_info_ids.mapped('product_id').message_subscribe(partner_ids=seller.ids)
                if removel_ids:
                    rec.seller_info_ids.mapped('product_id').message_unsubscribe(partner_ids=removel_ids.ids)

        res = super(ResPartner, self).write(vals)

        if vals.get('default_shipping') or vals.get('type'):
            for record in self:
                if record.parent_id and record.default_shipping:
                    existing_defaults = self.search([('parent_id','=',record.parent_id.id),('type','=',record.type),('id','!=',record.id),('default_shipping','=', True)])
                    if existing_defaults:
                        existing_defaults.write({'default_shipping':False})
                        record.default_shipping = True
        return res

    @api.model
    def setup_pricelist_for_new_customer(self):
        name = self.customer_code + ' - ' + self.name
        pricelist = self.env['product.pricelist'].create({
            'name': name,
            'type': 'customer'})
        self.env['customer.pricelist'].create({'pricelist_id': pricelist.id,
                                               'sequence': 1,
                                               'partner_id': self.id})
        return True


ResPartner()


class ResPartnerCategory(models.Model):
    _inherit = 'res.partner.category'

    code = fields.Char(string='Code')


ResPartnerCategory()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
