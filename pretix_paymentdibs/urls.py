from django.conf.urls import include, url

from pretix.multidomain import event_url
from .views import callback, redirect_view, ReturnView

event_patterns = [
    url(r'^pretix_paymentdibs/', include([
        event_url(r'^webhook/(?P<payment>[0-9]+)/$', callback, name='webhook', require_live=False),
        url(r'^redirect/$', redirect_view, name='redirect'),
        url(r'^return/(?P<order>[^/]+)/(?P<hash>[^/]+)/(?P<payment>[0-9]+)/(?P<action>[^/]+)$', ReturnView.as_view(),
            name='return'),
    ])),
]
