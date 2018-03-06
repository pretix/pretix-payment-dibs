from django.conf.urls import include, url

from pretix.multidomain import event_url

from .views import abort, redirect_view, success, callback

# Frontend patterns
event_patterns = [
    url(r'^pretix_paymentdibs/', include([
        url(r'^abort/$', abort, name='abort'),
        url(r'^return/$', success, name='return'),
        url(r'^redirect/$', redirect_view, name='redirect'),

        url(r'w/(?P<cart_namespace>[a-zA-Z0-9]{16})/abort/', abort, name='abort'),
        url(r'w/(?P<cart_namespace>[a-zA-Z0-9]{16})/return/', success, name='return'),

        event_url(r'^callback/$', callback, name='callback', require_live=False),
    ])),
]

urlpatterns = [
    url(r'^_pretix_paymentdibs/callback/$', callback, name='callback'),
]
