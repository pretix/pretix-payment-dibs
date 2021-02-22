from django.apps import AppConfig
from django.utils.translation import ugettext_lazy


class PluginApp(AppConfig):
    name = 'pretix_paymentdibs'
    verbose_name = 'DIBS'

    class PretixPluginMeta:
        name = ugettext_lazy('Nets / DIBS')
        author = 'Mikkel Ricky'
        description = ugettext_lazy('Card payment using Scandinavic payment provider Nets / DIBS')
        visible = True
        category = 'PAYMENT'
        version = '1.0.0'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_paymentdibs.PluginApp'
