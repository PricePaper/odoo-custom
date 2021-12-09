odoo.define('batch_delivery.price_lock', function (require) {
"use strict";

var AbstractField = require('web.AbstractField');
var core = require('web.core');
var field_registry = require('web.field_registry');
var field_utils = require('web.field_utils');
var viewDialogs = require('web.view_dialogs');

var QWeb = core.qweb;


var PriceLock = AbstractField.extend({
    events: _.extend({
        'click .js_price_lock': '_openPriceList',
    }, AbstractField.prototype.events),
    supportedFieldTypes: ['char'],

    init: function () {
        this._super.apply(this, arguments);
        this.info = JSON.parse(this.value) || {};
    },

    isSet: function() {
        return true;
    },

    _render: function() {
        var self = this;
        var info = this.info
        if (!info) {
            this.$el.html('');
            return;
        }
        let b = $("<a/>");
        b.addClass("js_price_lock fa fa-info-circle text-success");
        b.attr('title', info.title);
        b.attr('role', 'button');
        b.attr('aria-label', 'Info');
        b.attr('price-form', info.record);
        b.css('margin-right','5px');
        this.$el.html(b);
    },

    _openPriceList: function (event) {
        event.stopPropagation();
        event.preventDefault();
        var deferred = $.Deferred();
        var self = this;
        var priceFormId = parseInt($(event.target).attr('price-form'));
        if (isNaN(priceFormId)){
            this.do_notify("Alert!!", "Please save the line first in order to see the price form.", true);
        }
        else{
            var dialog = new viewDialogs.FormViewDialog(self, {
                res_model: 'customer.product.price',
                res_id: priceFormId,
                readonly: true,
                title: "Customer Product Price",
            }).open();
            dialog.on('closed', self, function () {
                deferred.resolve();
            });
        }
    },

});

field_registry.add('price_lock', PriceLock);

return {
    ShowPriceLock: PriceLock
};
    
});
