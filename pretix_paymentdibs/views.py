import json
import logging

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import get_template
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from pretix.base.models import Order
from pretix.base.services.orders import mark_order_paid
from pretix.multidomain.urlreverse import build_absolute_uri

logger = logging.getLogger('pretix.plugins.payment_dibs')


@xframe_options_exempt
def redirect_view(request, *args, **kwargs):
    order_id = request.session['payment_dibs_order_id']
    order = Order.objects.get(pk=order_id)

    amount = int(100 * order.total)
    currency = request.event.currency.upper()
    merchant_id = request.session['payment_dibs_merchant_id']
    test_mode = request.session['payment_dibs_test_mode']

    callback_url = build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:callback')
    accept_url = build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:return')

    template = 'pretix_paymentdibs/redirect.html'
    ctx = {
        'order_id': order_id,
        'order': order,
        'callback_url': callback_url,
        'accept_url': accept_url,
        'amount': amount,
        'currency': currency,
        'merchant_id': merchant_id,
        'test_mode': test_mode
    }

    return render(request, template, ctx)


@csrf_exempt
def success(request, *args, **kwargs):
    # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_pages
    parameters = request.POST if request.method == 'POST' else request.GET
    order_id = parameters.get('orderid')
    order = Order.objects.get(code=order_id)

    urlkwargs = {
        'order': order.code,
        'secret': order.secret
    }
    if 'cart_namespace' in kwargs:
        urlkwargs['cart_namespace'] = kwargs['cart_namespace']

    return redirect(build_absolute_uri(request.event, 'presale:event.order', kwargs=urlkwargs))


def abort(request, **kwargs):
    raise Exception('abort')


@csrf_exempt
def callback(request, **kwargs):
    # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_pages
    # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_parameters
    parameters = request.POST if request.method == 'POST' else request.GET

    order_id = parameters.get('orderid')
    order = Order.objects.get(code=order_id)
    # @see https://tech.dibspayment.com/nodeaddpage/toolboxstatuscodes
    status_code = parameters.get('statuscode')

    if int(status_code) == 2:
        template = get_template('pretix_paymentdibs/mail_text.html')
        ctx = {
            'order': order,
            'info': parameters
        }

        mail_text = template.render(ctx)
        mark_order_paid(order, 'dibs', send_mail=True, info=json.dumps(parameters), mail_text=mail_text)

    return HttpResponse(status=200)
