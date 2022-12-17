from django.urls import include, path

from pretix.multidomain import event_url
from .views import callback, redirect_view, ReturnView

event_patterns = [
    path('pretix_paymentdibs/', include([
        event_url(r'^webhook/(?P<payment>[0-9]+)/$', callback, name='webhook', require_live=False),
        path('redirect/', redirect_view, name='redirect'),
        path('return/<str:order>/<str:hash>/<int:payment>/<str:action>', ReturnView.as_view(),
            name='return'),
    ])),
]
