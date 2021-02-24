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
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _

from pretix.base.forms import SecretKeySettingsField
from pretix.base.models import Event, Order, Organizer, OrderPayment, Quota, OrderRefund
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.services.mail import SendMailException
from pretix.base.services.orders import mark_order_paid
from pretix.multidomain.urlreverse import build_absolute_uri

logger = logging.getLogger('pretix.plugins.payment_dibs')


class DIBS(BasePaymentProvider):
    identifier = 'dibs'
    verbose_name = _('Nets / DIBS')
    public_name = _('Card or MobilePay')
    payment_form_fields = OrderedDict([])

    # https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard
    CARD_TYPE_CREDIT = 'credit'
    CARD_TYPE_DEBIT = 'debit'

    # https://tech.dibspayment.com/D2/Toolbox/Paytypes
    #
    # 'AAK', # Århus city kort
    # 'ACCEPT', # Acceptcard
    # 'ACK', # Albertslund Centrum Kundekort
    # 'AKK', # Apollo-/Kuonikonto
    # 'AMEX', # American Express
    # 'AMEX(DK)', # American Express (DK)
    # 'AMEX(SE)', # American Express (SE)
    # 'BHBC', # Bauhaus BestCard
    # 'CCK', # Computer City
    # 'DAELLS', # Daells Bolighus Kundekort
    # 'DIN', # Diners Club
    # 'DIN(DK)', # Diners Club (DK)
    # 'DKW', # Dankort app
    # 'EWORLD', # Electronic World Credit Card
    # 'FCC', # Ford CreditCard
    # 'FCK', # Frederiksberg Centret Kundekort
    # 'FFK', # Forbrugsforeningen
    # 'FINX(SE)', # Finax (SE)
    # 'FISC', # Fields Shoppingcard
    # 'FLEGCARD', # Fleggard kort
    # 'FSC', # Fisketorvet Shopping Card
    # 'GIT', # Getitcard
    # 'GSC', # Glostrup Shopping Card
    # 'HEME', # Hemtex faktura
    # 'HEMP', # Hemtex personalkort
    # 'HEMTX', # Hemtex clubkort
    # 'HMK', # HM Konto
    # 'HNYBORG', # Harald Nyborg
    # 'HSC', # Hillerød Shopping Card
    # 'HTX', # Hydro Texaco
    # 'IBC', # Inspiration Best Card
    # 'IKEA', # IKEA kort
    # 'ISHBY', # Sparbank Vestkort
    # 'JCB', # JCB
    # 'JEM_FIX', # Jem&amp;Fix Kundekort
    # 'KAUPBK', # Kaupthing Bankkort
    # 'LFBBK', # Länsförsäkringar Bank Bankkort
    # 'LIC(DK)', # LIC kort (DK)
    # 'LIC(SE)', # LIC kort (SE)
    # 'LOPLUS', # LO Plus Guldkort
    # 'MEDM', # Medmera
    # 'MERLIN', # Merlin Kreditkort
    # 'MGNGC', # Magasin Goodie Card
    # 'MPO_Nets', # MobilePay Online (Nets)
    # 'MTRO', # Maestro
    # 'MTRO(DK)', # Maestro (DK)
    # 'MTRO(UK)', # Maestro (UK)
    # 'MTRO(SOLO)', # Solo
    # 'MTRO(SE)', # Maestro (SE)
    # 'MYHC', # My Holiday Card
    # 'NSBK', # Nordea Bankkort
    # 'OESBK', # Östgöta Enskilda Bankkort
    # 'Q8SK', # Q8 ServiceKort
    # 'REB', # Resurs Bank
    # 'REMCARD', # Remember Card
    # 'ROEDCEN', # Rødovre Centerkort
    # 'S/T', # Spies/Tjæreborg
    # 'SBSBK', # Skandiabanken Bankkort
    # 'SEB_KOBK', # SEB Köpkort
    # 'SEBSBK', # SEB Bankkort
    # 'SHB_KB', # Handelsbanken Köpkort
    # 'SILV_ERHV', # Silvan Konto Erhverv
    # 'SILV_PRIV', # Silvan Konto Privat
    # 'STARTOUR', # Star Tour
    # 'TLK', # Tæppeland
    # 'TUBC', # Toys R Us - BestCard
    # 'VEKO', # VEKO Finans
    # 'WOCO', # Wonderful Copenhagen Card
    CARD_TYPES = {
        CARD_TYPE_CREDIT: [
            'ELEC',         # VISA Electron
            'MC',           # Mastercard
            'MC(DK)',       # Mastercard (DK)
            'MC(SE)',       # Mastercard (SE)
            'MC(YX)',       # YX Mastercard
            'VISA',         # VISA
            'VISA(DK)',     # VISA (DK)
            'VISA(SE)',     # VISA (SE)
        ],
        CARD_TYPE_DEBIT: [
            'DK',           # Dankort
            'V-DK',         # VISA-Dankort
        ]
    }

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
            ('md5_key1',
             forms.CharField(
                 label=_('MD5 key 1'),
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
             )),
            ('api_user',
             forms.CharField(
                 label=_('API Username'),
                 required=False,
                 help_text=_('Required for refunds. Can be set up at Setup > User Setup > API users.').format(
                     docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                 )
             )),
            ('api_password',
             SecretKeySettingsField(
                 label=_('API Password'),
                 required=False,
                 help_text=_('Required for refunds. Can be set up at Setup > User Setup > API users.').format(
                     docs_url='https://tech.dibspayment.com/D2/Hosted/Input_parameters/Standard'
                 )
             )),

        ] + list(super().settings_form_fields.items()))
        d.move_to_end('_enabled', last=False)

        return d

    def payment_is_valid_session(self, request):
        return True

    def payment_form_render(self, request, total, order=None) -> str:
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

    def checkout_confirm_render(self, request, order=None) -> str:
        template = get_template('pretix_paymentdibs/checkout_confirm.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings
        }
        return template.render(ctx)

    def execute_payment(self, request, payment) -> str:
        return self._redirect_to_dibs(request, payment)

    def payment_prepare(self, request, order):
        return True

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        return all(self.get_api_authorization())

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return all(self.get_api_authorization())

    def execute_refund(self, refund):
        info = refund.payment.info_data
        merchant = self.settings.get('merchant_id')
        transact = info['transact']
        currency = info['currency']
        orderid = info['orderid']

        payload = {
            'merchant': merchant,
            'transact': transact,
            'amount': DIBS.get_amount(refund.amount),
            'currency': currency,
            'orderid': orderid,
            'textreply': 'true',
            # 'fullreply': 'true'
        }

        if self.settings.get('test_mode'):
            payload['test'] = 1

        # https://tech.dibspayment.com/D2/API/MD5
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')

        parameters = 'merchant=' + merchant + '&orderid=' + orderid + '&transact=' + transact + '&amount=' + DIBS.get_amount(refund.amount)
        md5key = DIBS.md5(key2 + DIBS.md5(key1 + parameters))
        payload['md5key'] = md5key

        (username, password) = self.get_api_authorization()
        if username is None or password is None:
            raise PaymentException(_('Missing DIBS api username and password for merchant {merchant}.'
                                     ' Order cannot be refunded in DIBS.').format(merchant=merchant))

        # https://tech.dibspayment.com/D2/API/Payment_functions/refundcgi
        url = 'https://{}:{}@payment.architrade.com/cgi-adm/refund.cgi'.format(username, password)

        r = requests.post(url, data=payload)

        data = parse_qs(r.text)
        status = data['status'][0] if 'status' in data else None
        result = int(data['result'][0]) if 'result' in data else -1
        message = data['message'][0] if 'message' in data else None
        refund.info_data = data

        if result == DIBS.REFUND_ACCEPTED:
            refund.done()
        else:
            refund.state = OrderRefund.REFUND_STATE_FAILED
            refund.execution_date = now()
            refund.save()
            raise PaymentException(_('Error refunding in DIBS ({status}; {result}; {message})'.format(status=status, result=result, message=message.strip())))

    def get_api_authorization(self):
        return self.settings.get('api_user'), self.settings.get('api_password')

    def payment_control_render(self, request, payment) -> str:
        template = get_template('pretix_paymentdibs/control.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
            'payment_info': payment.info_data,
            'payment': payment,
            'provider': self,
        }
        return template.render(ctx)

    @property
    def currency_code(self):
        return str(pycountry.currencies.get(alpha_3=self.event.currency).numeric)

    @staticmethod
    def get_amount(total):
        return str(int(100 * total))

    def get_order_id(self, payment):
        """
        Construct unique DIBS order id.
        Order codes are only unique within events.
        """
        return self.event.organizer.slug + '/' + self.event.slug + '/' + payment.order.code + '/' + str(payment.local_id)

    @staticmethod
    def get_payment_card_type(order):
        """
        Get the payment card type, "credit","debit" or None.
        """
        info = json.loads(order.payment_info)
        paytype = info['paytype'] if 'paytype' in info else None

        for type, paytypes in DIBS.CARD_TYPES.items():
            if paytype in paytypes:
                return type

        return None

    @staticmethod
    def get_order_payment(order_id):
        """Get orderpayment from DIBS order id"""
        # An order code only contains alphanumeric characters.
        match = re.search('^(?P<organizer>.+)/(?P<event>.+)/(?P<code>.+)/(?P<payment>[0-9]+)$', order_id)
        if match is None:
            return None
        event = Event.objects.get(organizer__slug=match.group('organizer'), slug=match.group('event'))
        return OrderPayment.objects.get(order__code=match.group('code'), order__event=event, local_id=match.group('payment'))

    def _redirect_to_dibs(self, request, payment):
        self.set_payment_info(request, payment)
        return build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:redirect')

    def set_payment_info(self, request, payment):
        request.session['payment_dibs_payment_info'] = {
            'order_id': self.get_order_id(payment),
            'order_code': payment.order.code,
            'order_secret': payment.order.secret,
            'payment_id': payment.pk,
            'amount': int(100 * payment.amount),
            'currency': self.currency_code,
            'merchant_id': self.settings.get('merchant_id'),
            'test_mode': self.settings.get('test_mode') == 'True',
            'md5key': self._calculate_md5key(payment),
            'decorator': self.settings.get('decorator'),
            'capturenow': self.settings.get('capturenow') == 'True',
            'ordertext': None
        }

    @staticmethod
    def get_payment_info(request):
        return request.session['payment_dibs_payment_info']

    @staticmethod
    def process_callback(request, log=True):
        # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_pages
        # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_parameters
        parameters = request.POST if request.method == 'POST' else request.GET

        order_id = parameters.get('orderid')
        payment = DIBS.get_order_payment(order_id)

        if payment.provider != DIBS.identifier or payment.order.event != request.event:
            return False

        info = json.loads(json.dumps(parameters))
        info['currency_code'] = info['currency']
        info['currency'] = pycountry.currencies.get(numeric=info['currency']).alpha_3
        info['statuscode'] = int(info['statuscode'])
        status_code = info['statuscode']

        payment.order.log_action('pretix_paymentdibs.callback', data=info)

        if status_code in {DIBS.STATUS_CODE_AUTHORIZATION_APPROVED, DIBS.STATUS_CODE_CAPTURE_COMPLETED}:
            payment_provider = payment.payment_provider
            if payment_provider.validate_transaction(payment, parameters):
                try:
                    payment.info_data = info
                    payment.confirm()
                except Quota.QuotaExceededException as e:
                    raise PaymentException(str(e))
                except SendMailException:
                    raise PaymentException(_('There was an error sending the confirmation mail.'))

    def validate_transaction(self, payment, parameters):
        # https://tech.dibspayment.com/D2/API/MD5
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')

        transact = parameters['transact']
        currency = self.currency_code
        amount = DIBS.get_amount(payment.amount)

        authkey = DIBS.md5(key2 + DIBS.md5(key1 + 'transact=' + transact + '&amount=' + amount + '&currency=' + currency))

        return parameters['authkey'] == authkey

    def _calculate_md5key(self, payment):
        # https://tech.dibspayment.com/D2/Hosted/Md5_calculation
        key1 = self.settings.get('md5_key1')
        key2 = self.settings.get('md5_key2')
        merchant = self.settings.get('merchant_id')
        orderid = self.get_order_id(payment)
        currency = self.currency_code
        amount = DIBS.get_amount(payment.amount)

        parameters = 'merchant=' + merchant + '&orderid=' + orderid + '&currency=' + currency + '&amount=' + amount
        inner_md5 = DIBS.md5(key1 + parameters)
        md5key = DIBS.md5(key2 + inner_md5)

        return md5key

    @staticmethod
    def md5(s):
        """Calculate md5 hash of a string"""
        return hashlib.md5(s.encode('utf-8')).hexdigest()
