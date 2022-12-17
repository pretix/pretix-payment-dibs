from django.apps import AppConfig
from django.utils.translation import gettext_lazy
from . import __version__


class PluginApp(AppConfig):
    name = 'pretix_paymentdibs'
    verbose_name = 'DIBS'

    class PretixPluginMeta:
        name = gettext_lazy('Nets / DIBS')
        author = 'Mikkel Ricky'
        description = gettext_lazy('Accept card payments using Scandinavic payment provider Nets / DIBS. <span class="text-danger">Do not use this plugin for new integrations, it uses a deprecated API that will be disabled by Nets soon. Use the "nets Easy Payments" plugin instead.</span>')
        visible = True
        category = 'PAYMENT'
        version = __version__

    def ready(self):
        from . import signals  # NOQA

