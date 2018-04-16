import hashlib
import json
import logging
import re
from collections import OrderedDict

import pycountry
from django import forms
from django.template.loader import get_template
from django.utils.translation import ugettext_lazy as _
from pretix.base.models import Event, Order, Organizer
from pretix.base.payment import BasePaymentProvider
from pretix.base.services.orders import mark_order_paid
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
                     required=False,
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
                 )),
                ('capturenow',
                 forms.BooleanField(
                     label=_('capturenow'),
                     required=False,
                     initial=False,
                     help_text=_('(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                         docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                     )
                 )),
                ('use_md5key',
                 forms.BooleanField(
                     label=_('MD5-control of payments'),
                     required=False,
                     initial=False,
                     help_text=_('MD5-control of payments '
                                 '(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                         docs_url='https://tech.dibspayment.com/D2/API/MD5'
                     )
                 )),
                ('md5_key1',
                 forms.CharField(
                     label=_('Key 1'),
                     required=False,
                     min_length=32,
                     max_length=32,
                     help_text=_('Key 1 (32 characters)'
                                 '(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)'
                                 ' (required if "{parent_control}" is set)').format(
                         docs_url='https://tech.dibspayment.com/D2/API/MD5',
                         parent_control=_('MD5-control of payments')
                     )
                 )),
                ('md5_key2',
                 forms.CharField(
                     label=_('Key 2'),
                     required=False,
                     min_length=32,
                     max_length=32,
                     help_text=_('Key 2 (32 characters)'
                                 '(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)'
                                 ' (required if "{parent_control}" is set)').format(
                         docs_url='https://tech.dibspayment.com/D2/API/MD5',
                         parent_control=_('MD5-control of payments')
                     )
                 )),
                ('decorator',
                 forms.ChoiceField(
                     label=_('Decorator'),
                     choices=(
                         ('default', _('default')),
                         ('basal', _('basal')),
                         ('rich', _('rich')),
                         ('responsive', _('responsive'))
                     ),
                     initial='default',
                     help_text=_('(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                         docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                     )
                 ))
            ]
        )

    def settings_content_render(self, request):
        pass

    def payment_is_valid_session(self, request):
        return True

    def payment_form_render(self, request) -> str:
        template = get_template('pretix_paymentdibs/payment_form.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
            'info': request.GET
        }
        return template.render(ctx)

    def checkout_prepare(self, request, cart):
        return True

    def checkout_confirm_render(self, request) -> str:
        template = get_template('pretix_paymentdibs/checkout_confirm.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings
        }
        return template.render(ctx)

    def payment_perform(self, request, order) -> str:
        return self._redirect_to_dibs(request, order)

    def order_pending_render(self, request, order) -> str:
        template = get_template('pretix_paymentdibs/order_pending.html')
        ctx = {
            'request': request,
            'event': self.event,
            'order': order
        }
        return template.render(ctx)

    def order_pending_mail_render(self, order) -> str:
        template = get_template('pretix_paymentdibs/order_pending_mail.html')
        ctx = {
            'event': self.event,
            'order': order
        }
        return template.render(ctx)

    def order_paid_render(self, request, order) -> str:
        template = get_template('pretix_paymentdibs/order_paid.html')
        info = None if order.payment_info is None else json.loads(order.payment_info)
        ctx = {
            'request': request,
            'order': order,
            'event': self.event,
            'info': info
        }
        return template.render(ctx)

    def order_can_retry(self, order):
        return self._is_still_available(order=order)

    def order_prepare(self, request, order):
        return self._redirect_to_dibs(request, order)

    @staticmethod
    def get_currency(order):
        return str(pycountry.currencies.get(alpha_3=order.event.currency).numeric)

    @staticmethod
    def get_amount(order):
        return str(int(100 * order.total))

    @staticmethod
    def get_order_id(order):
        """
        Construct unique DIBS order id.
        Order codes are only unique within events.
        """
        return order.event.organizer.slug + '/' + order.event.slug + '/' + order.code

    @staticmethod
    def get_order(order_id):
        """Get order from DIBS order id"""
        # An order code only contains alphanumeric characters.
        match = re.search('^(?P<organizer>.+)/(?P<event>.+)/(?P<code>.+)$', order_id)
        if match is None:
            return None
        organizer = Organizer.objects.get(slug=match.group('organizer'))
        event = Event.objects.get(organizer=organizer.id, slug=match.group('event'))

        return Order.objects.get(code=match.group('code'), event=event.id)

    def _redirect_to_dibs(self, request, order):
        self.set_payment_info(request, order)

        return build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:redirect')

    def set_payment_info(self, request, order):
        request.session['payment_dibs_payment_info'] = json.dumps({
            'order_id': DIBS.get_order_id(order),
            'amount': int(100 * order.total),
            'currency': DIBS.get_currency(order),
            'merchant_id': self.settings.get('merchant_id'),
            'test_mode': self.settings.get('test_mode') == 'True',
            'md5key': self._calculate_md5key(order),
            'decorator': self.settings.get('decorator'),
            'capturenow': self.settings.get('capturenow') == 'True',
            'ordertext': None
        })

    @staticmethod
    def get_payment_info(request):
        info = json.loads(request.session['payment_dibs_payment_info'])

        return info

    @staticmethod
    def validate_callback(request):
        # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_pages
        # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_parameters
        parameters = request.POST if request.method == 'POST' else request.GET

        order_id = parameters.get('orderid')
        order = DIBS.get_order(order_id)

        if order.payment_provider != DIBS.identifier:
            return False

        status_code = int(parameters.get('statuscode'))

        # @see https://tech.dibspayment.com/nodeaddpage/toolboxstatuscodes
        # 2: authorization approved	The transaction is approved by acquirer.
        # 5: capture completed
        if status_code == 2 or status_code == 5:
            payment_provider = order.event.get_payment_providers()[order.payment_provider]
            if payment_provider.validate_transaction(order, parameters):
                template = get_template('pretix_paymentdibs/mail_text.html')
                ctx = {
                    'order': order,
                    'info': parameters
                }

                mail_text = template.render(ctx)
                # https://tech.dibspayment.com/D2/API/Payment_functions/capturecgi
                mark_order_paid(order, DIBS.identifier, send_mail=True, info=json.dumps(parameters), mail_text=mail_text)

                return True

        return False

    def validate_transaction(self, order, parameters):
        if not self.settings.get('use_md5key'):
            return True

        # https://tech.dibspayment.com/D2/API/MD5
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')

        transact = parameters['transact']
        currency = DIBS.get_currency(order)
        amount = DIBS.get_amount(order)

        authkey = DIBS.md5(key2 + DIBS.md5(key1 + 'transact=' + transact + '&amount=' + amount + '&currency=' + currency))

        logger.debug(['validate_transaction', key1, key2, transact, currency, amount, authkey, parameters['authkey'] == authkey, parameters])

        return parameters['authkey'] == authkey

    def _calculate_md5key(self, order):
        if not self.settings.get('use_md5key'):
            return None

        # https://tech.dibspayment.com/D2/Hosted/Md5_calculation
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')
        merchant = self.settings.get('merchant_id')
        orderid = DIBS.get_order_id(order)
        currency = DIBS.get_currency(order)
        amount = DIBS.get_amount(order)

        parameters = 'merchant=' + merchant + '&orderid=' + orderid + '&currency=' + currency + '&amount=' + amount
        inner_md5 = DIBS.md5(key1 + parameters)
        md5key = DIBS.md5(key2 + inner_md5)

        return md5key

    @staticmethod
    def md5(s):
        """Calculate md5 hash of a string"""
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def order_control_refund_render(self, order, request):
        pass

    def order_control_refund_perform(self, request, order):
        # https://tech.dibspayment.com/D2/API/Payment_functions/refundcgi
        pass
