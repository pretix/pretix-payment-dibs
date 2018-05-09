import hashlib
import json
import logging
import re
from collections import OrderedDict
from urllib.parse import parse_qs

import pycountry
import requests
from django import forms
from django.contrib import messages
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

    # https://tech.dibspayment.com/nodeaddpage/toolboxstatuscodes
    STATUS_CODE_TRANSACTION_INSERTED = 0
    STATUS_CODE_DECLINED = 1
    STATUS_CODE_AUTHORIZATION_APPROVED = 2
    STATUS_CODE_CAPTURE_SENT_TO_ACQUIRER = 3
    STATUS_CODE_CAPTURE_DECLINED_BY_ACQUIRER = 4
    STATUS_CODE_CAPTURE_COMPLETED = 5
    STATUS_CODE_AUTHORIZATION_DELETED = 6
    STATUS_CODE_CAPTURE_BALANCED = 7
    STATUS_CODE_PARTIALLY_REFUNDED_AND_BALANCED = 8
    STATUS_CODE_REFUND_SENT_TO_ACQUIRER = 9
    STATUS_CODE_REFUND_DECLINED = 10
    STATUS_CODE_REFUND_COMPLETED = 11
    STATUS_CODE_CAPTURE_PENDING = 12
    STATUS_CODE_TICKET_TRANSACTION = 13
    STATUS_CODE_DELETED_TICKET_TRANSACTION = 14
    STATUS_CODE_REFUND_PENDING = 15
    STATUS_CODE_WAITING_FOR_SHOP_APPROVAL = 16
    STATUS_CODE_DECLINED_BY_DIBS = 17
    STATUS_CODE_MULTICAP_TRANSACTION_OPEN = 18
    STATUS_CODE_MULTICAP_TRANSACTION_CLOSED = 19
    STATUS_CODE_POSTPONED = 26

    # https://tech.dibspayment.com/D2/API/Error_codes
    REFUND_ACCEPTED = 0
    REFUND_NO_RESPONSE_FROM_ACQUIRER = 1
    REFUND_TIMEOUT = 2
    REFUND_CREDIT_CARD_EXPIRED = 3
    REFUND_REJECTED_BY_ACQUIRER = 4
    REFUND_AUTHORISATION_OLDER_THAN_7_DAYS = 5
    REFUND_TRANSACTION_STATUS_ON_THE_DIBS_SERVER_DOES_NOT_ALLOW_FUNCTION = 6
    REFUND_AMOUNT_TOO_HIGH = 7
    REFUND_ERROR_IN_THE_PARAMETERS_SENT_TO_THE_DIBS_SERVER = 8
    REFUND_ORDER_NUMBER_ORDERID_DOES_NOT_CORRESPOND_TO_THE_AUTHORISATION_ORDER_NUMBER = 9
    REFUND_RE_AUTHORISATION_OF_THE_TRANSACTION_WAS_REJECTED = 10
    REFUND_NOT_ABLE_TO_COMMUNICATE_WITH_THE_ACQUIER = 11
    REFUND_CONFIRM_REQUEST_ERROR = 12
    REFUND_CAPTURE_IS_CALLED_FOR_A_TRANSACTION_WHICH_IS_PENDING_FOR_BATCH_I_E_CAPTURE_WAS_ALREADY_CALLED = 14
    REFUND_CAPTURE_OR_REFUND_WAS_BLOCKED_BY_DIBS = 15

    @property
    def settings_form_fields(self):
        d = OrderedDict([
            ('merchant_id',
             forms.CharField(
                 label=_('Merchant ID'),
                 min_length=2,
                 max_length=16,
                 help_text=_('The Merchant ID issued by DIBS')
             )),
            ('test_mode',
             forms.BooleanField(
                 label=_('Test mode'),
                 required=False,
                 initial=False,
                 help_text=_('If checked, payments will be processed in test mode '
                             '(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                     docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                 )
             )),
            ('capturenow',
             forms.BooleanField(
                 label=_('Capture now'),
                 required=False,
                 initial=False,
                 help_text=_('If set, payments will be captured immediately'
                             ' (cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                     docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                 )
             )),
            ('use_md5key',
             forms.BooleanField(
                 label=_('MD5-control of payments'),
                 required=False,
                 initial=False,
                 help_text=_('MD5-control of payments'
                             ' (cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                     docs_url='https://tech.dibspayment.com/D2/API/MD5'
                 )
             )),
            ('md5_key1',
             forms.CharField(
                 label=_('MD5 key 1'),
                 required=False,
                 min_length=32,
                 max_length=32,
                 help_text=_('MD5 key 1 (32 characters)'
                             ' (cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)'
                             ' (required if "{parent_control}" is set)').format(
                     docs_url='https://tech.dibspayment.com/D2/API/MD5',
                     parent_control=_('MD5-control of payments')
                 )
             )),
            ('md5_key2',
             forms.CharField(
                 label=_('MD5 key 2'),
                 required=False,
                 min_length=32,
                 max_length=32,
                 help_text=_('MD5 key 2 (32 characters)'
                             ' (cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)'
                             ' (required if "{parent_control}" is set)').format(
                     docs_url='https://tech.dibspayment.com/D2/API/MD5',
                     parent_control=_('MD5-control of payments')
                 )
             )),
            ('decorator',
             forms.ChoiceField(
                 label=_('Decorator'),
                 choices=(
                     ('default', _('Default')),
                     ('basal', _('Basal')),
                     ('rich', _('Rich')),
                     ('responsive', _('Responsive'))
                 ),
                 initial='default',
                 help_text=_('(cf. <a target="_blank" rel="noopener" href="{docs_url}">{docs_url}</a>)').format(
                     docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                 )
             ))
        ] + list(super().settings_form_fields.items()))
        d.move_to_end('_enabled', last=False)

        return d

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
        info = json.loads(order.payment_info)
        ctx = {
            'request': request,
            'order': order,
            'event': self.event,
            'info': info,
            'status': 'captured' if int(info['statuscode']) == DIBS.STATUS_CODE_CAPTURE_COMPLETED else 'reserved'
        }
        return template.render(ctx)

    def order_can_retry(self, order):
        return self._is_still_available(order=order)

    def order_prepare(self, request, order):
        return self._redirect_to_dibs(request, order)

    def order_control_refund_render(self, order, request):
        merchant = self.settings.get('merchant_id')
        (username, password) = self.get_api_authorization(merchant)
        if username is None or password is None:
            messages.error(request, _('Missing DIBS api username and password for merchant {merchant}.'
                                      ' Order cannot be refunded in DIBS.').format(merchant=merchant))

        template = get_template('pretix_paymentdibs/control_refund.html')
        info = json.loads(order.payment_info)
        ctx = {
            'request': request,
            'event': self.event,
            'info': info,
            'order': order
        }
        return template.render(ctx)

    def order_control_refund_perform(self, request, order):
        info = json.loads(order.payment_info)
        merchant = self.settings.get('merchant_id')
        transact = info['transact']
        amount = info['amount']
        currency = info['currency']
        orderid = info['orderid']

        payload = {
            'merchant': merchant,
            'transact': transact,
            'amount': amount,
            'currency': currency,
            'orderid': orderid,
            'textreply': 'true',
            # 'fullreply': 'true'
        }

        if self.settings.get('test_mode'):
            payload['test'] = 1

        if self.settings.get('use_md5key'):
            # https://tech.dibspayment.com/D2/API/MD5
            key1 = self.settings.get('md5_key1')
            key2 = self.settings.get('md5_key2')

            parameters = 'merchant=' + merchant + '&orderid=' + orderid + '&transact=' + transact + '&amount=' + amount
            md5key = DIBS.md5(key2 + DIBS.md5(key1 + parameters))
            payload['md5key'] = md5key

        (username, password) = self.get_api_authorization(merchant)
        if username is None or password is None:
            messages.error(request, _('Missing DIBS api username and password for merchant {merchant}.'
                                      ' Order cannot be refunded in DIBS.').format(merchant=merchant))
            return None

        # https://tech.dibspayment.com/D2/API/Payment_functions/refundcgi
        url = 'https://{}:{}@payment.architrade.com/cgi-adm/refund.cgi'.format(username, password)

        r = requests.post(url, data=payload)

        data = parse_qs(r.text)
        status = data['status'][0] if 'status' in data else None
        result = int(data['result'][0]) if 'result' in data else -1
        message = data['message'][0] if 'message' in data else None

        if result == DIBS.REFUND_ACCEPTED:
            from pretix.base.services.orders import mark_order_refunded

            mark_order_refunded(order, user=request.user)
            messages.success(request, _('The order has been marked as refunded and the money have been refunded in DIBS.'))
        else:
            messages.error(request, _('Error refunding in DIBS ({status}; {result}; {message})'.format(status=status, result=result, message=message)))
            logger.error(['order_control_refund_perform', r.text, r.status_code, info])

        return None

    def get_api_authorization(self, merchant):
        from pretix.settings import config

        section = 'pretix_paymentdibs'
        option = 'api_auth[{}]'.format(merchant)
        data = config.get(section, option) if config.has_option(section, option) else None

        try:
            return data.split(':')
        except Exception as e:
            return (None, None)

    @staticmethod
    def get_currency_code(order):
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
            'currency': DIBS.get_currency_code(order),
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

        info = json.loads(json.dumps(parameters))
        info['currency_code'] = info['currency']
        info['currency'] = pycountry.currencies.get(numeric=info['currency']).alpha_3
        info['statuscode'] = int(info['statuscode'])
        status_code = info['statuscode']

        if status_code in {DIBS.STATUS_CODE_AUTHORIZATION_APPROVED, DIBS.STATUS_CODE_CAPTURE_COMPLETED}:
            payment_provider = order.event.get_payment_providers()[order.payment_provider]
            if payment_provider.validate_transaction(order, parameters):
                template = get_template('pretix_paymentdibs/mail_text.html')
                ctx = {
                    'order': order,
                    'info': info,
                    'status': 'captured' if status_code == DIBS.STATUS_CODE_CAPTURE_COMPLETED else 'reserved'
                }

                mail_text = template.render(ctx)
                # https://tech.dibspayment.com/D2/API/Payment_functions/capturecgi
                mark_order_paid(order, DIBS.identifier, send_mail=True, info=json.dumps(info), mail_text=mail_text)

                return True

        return False

    def validate_transaction(self, order, parameters):
        if not self.settings.get('use_md5key'):
            return True

        # https://tech.dibspayment.com/D2/API/MD5
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')

        transact = parameters['transact']
        currency = DIBS.get_currency_code(order)
        amount = DIBS.get_amount(order)

        authkey = DIBS.md5(key2 + DIBS.md5(key1 + 'transact=' + transact + '&amount=' + amount + '&currency=' + currency))

        return parameters['authkey'] == authkey

    def _calculate_md5key(self, order):
        if not self.settings.get('use_md5key'):
            return None

        # https://tech.dibspayment.com/D2/Hosted/Md5_calculation
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')
        merchant = self.settings.get('merchant_id')
        orderid = DIBS.get_order_id(order)
        currency = DIBS.get_currency_code(order)
        amount = DIBS.get_amount(order)

        parameters = 'merchant=' + merchant + '&orderid=' + orderid + '&currency=' + currency + '&amount=' + amount
        inner_md5 = DIBS.md5(key1 + parameters)
        md5key = DIBS.md5(key2 + inner_md5)

        return md5key

    @staticmethod
    def md5(s):
        """Calculate md5 hash of a string"""
        return hashlib.md5(s.encode('utf-8')).hexdigest()
