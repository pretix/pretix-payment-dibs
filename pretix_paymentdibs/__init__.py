from django.apps import AppConfig
from django.utils.translation import ugettext_lazy


class PluginApp(AppConfig):
    name = 'pretix_paymentdibs'
    verbose_name = 'DIBS'

    class PretixPluginMeta:
        name = ugettext_lazy('Credit card payment using DIBS')
        author = 'Mikkel Ricky'
        description = ugettext_lazy('Credit card payment using DIBS')
        visible = True
        version = '1.0.0'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_paymentdibs.PluginApp'
