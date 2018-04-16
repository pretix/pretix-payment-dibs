import logging

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from pretix.multidomain.urlreverse import build_absolute_uri
from pretix_paymentdibs.payment import DIBS

logger = logging.getLogger('pretix.plugins.payment_dibs')


@xframe_options_exempt
def redirect_view(request, *args, **kwargs):
    info = DIBS.get_payment_info(request)
    template = 'pretix_paymentdibs/redirect.html'
    ctx = info.copy()
    ctx.update({
        'callback_url': build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:callback'),
        'accept_url': build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:return')
    })

    return render(request, template, ctx)


@csrf_exempt
def success(request, *args, **kwargs):
    # @see https://tech.dibspayment.com/D2/Hosted/Output_parameters/Return_pages
    parameters = request.POST if request.method == 'POST' else request.GET
    order_id = parameters.get('orderid')
    order = DIBS.get_order(order_id)

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
    DIBS.validate_callback(request)

    return HttpResponse(status=200)
