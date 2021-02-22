import hashlib
import logging

from django.contrib import messages
from django.http import HttpResponse, Http404
from django.shortcuts import redirect, render, get_object_or_404
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from pretix_paymentdibs.payment import DIBS

from pretix.base.models import Order, OrderPayment
from pretix.multidomain.urlreverse import build_absolute_uri, eventreverse

logger = logging.getLogger('pretix.plugins.payment_dibs')


@xframe_options_exempt
def redirect_view(request, *args, **kwargs):
    info = DIBS.get_payment_info(request)
    template = 'pretix_paymentdibs/redirect.html'
    ctx = info.copy()
    ctx.update({
        'callback_url': build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:webhook', kwargs={
            'payment': info['payment_id'],
        }),
        'accept_url': build_absolute_uri(request.event, 'plugins:pretix_paymentdibs:return', kwargs={
            'order': info['order_code'],
            'payment': info['payment_id'],
            'hash': hashlib.sha1(info['order_secret'].lower().encode()).hexdigest(),
            'action': 'success'
        }),
    })

    return render(request, template, ctx)


@csrf_exempt
def callback(request, **kwargs):
    DIBS.validate_callback(request)

    return HttpResponse(status=200)


class DIBSOrderView:
    def dispatch(self, request, *args, **kwargs):
        try:
            self.order = request.event.orders.get(code=kwargs['order'])
            if hashlib.sha1(self.order.secret.lower().encode()).hexdigest() != kwargs['hash'].lower():
                raise Http404('')
        except Order.DoesNotExist:
            # Do a hash comparison as well to harden timing attacks
            if 'abcdefghijklmnopq'.lower() == hashlib.sha1('abcdefghijklmnopq'.encode()).hexdigest():
                raise Http404('')
            else:
                raise Http404('')
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def payment(self):
        return get_object_or_404(self.order.payments,
                                 pk=self.kwargs['payment'],
                                 provider__startswith='dibs')

    @cached_property
    def pprov(self):
        return self.payment.payment_provider


@method_decorator(xframe_options_exempt, 'dispatch')
class ReturnView(DIBSOrderView, View):
    def get(self, request, *args, **kwargs):
        return self._redirect_to_order()

    def _redirect_to_order(self):
        self.order.refresh_from_db()
        info = DIBS.get_payment_info(self.request)
        if info.get('order_secret') != self.order.secret:
            messages.error(self.request, _('Sorry, there was an error in the payment process. Please check the link '
                                           'in your emails to continue.'))
            return redirect(eventreverse(self.request.event, 'presale:event.index'))

        return redirect(eventreverse(self.request.event, 'presale:event.order', kwargs={
            'order': self.order.code,
            'secret': self.order.secret
        }) + ('?paid=yes' if self.order.status == Order.STATUS_PAID else ''))
