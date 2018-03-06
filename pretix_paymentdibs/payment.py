import json
import logging
from collections import OrderedDict

from django import forms
from django.template.loader import get_template
from django.utils.translation import ugettext_lazy as _
from pretix.base.payment import BasePaymentProvider
from pretix.multidomain.urlreverse import build_absolute_uri

logger = logging.getLogger('pretix.plugins.payment_dibs')


class DIBS(BasePaymentProvider):
    identifier = 'dibs'
    verbose_name = _('DIBS')
    payment_form_fields = OrderedDict([
    ])
    # https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard

    @property
    def settings_form_fields(self):
        return OrderedDict(
            list(super().settings_form_fields.items()) + [
                ('test_mode',
                 forms.BooleanField(
                     label=_('Test mode'),
                     initial=False,
                     help_text=_('If "Test mode" is checked, payments will run in test mode '
                                 '(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                         docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                     )
                 )),
                ('merchant_id',
                 forms.CharField(
                     label=_('Merchant ID'),
                     min_length=2,
                     max_length=16,
                     help_text=_('The Merchant ID issued by DIBS')
                 ))
            ]
        )

    def settings_content_render(self, request):
        pass

    def payment_is_valid_session(self, request):
        return True

    def payment_form_render(self, request) -> str:
        template = get_template('pretixplugins/pretix_paymentdibs/checkout_payment_form.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings}
        return template.render(ctx)

    def checkout_prepare(self, request, cart):
        return True

    def checkout_confirm_render(self, request) -> str:
        template = get_template('pretixplugins/pretix_paymentdibs/checkout_confirm.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings}
        return template.render(ctx)

    def payment_perform(self, request, order) -> str:
        return self._redirect_to_dibs(request, order)

    def order_pending_render(self, request, order) -> str:
        template = get_template('pretixplugins/pretix_paymentdibs/payment_pending.html')
        ctx = {'request': request, 'order': order}
        return template.render(ctx)

    def order_paid_render(self, request, order) -> str:
        template = get_template('pretixplugins/pretix_paymentdibs/payment_paid.html')
        info = None if order.payment_info is None else json.loads(order.payment_info)
        ctx = {'request': request, 'order': order, 'info': info}
        return template.render(ctx)

    def order_can_retry(self, order):
        return self._is_still_available(order=order)

    def order_prepare(self, request, order):
        return self._redirect_to_dibs(request, order)

    def _redirect_to_dibs(self, request, order):
        request.session['payment_dibs_order_id'] = order.id
        request.session['payment_dibs_merchant_id'] = self.settings.get('merchant_id')
        request.session['payment_dibs_test_mode'] = self.settings.get('test_mode')

        return build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:redirect')
