from django.apps import AppConfig
from django.utils.translation import ugettext_lazy


class PluginApp(AppConfig):
    name = 'pretix_paymentdibs'
    verbose_name = 'DIBS'

    class PretixPluginMeta:
        name = ugettext_lazy('Nets / DIBS')
        author = 'Mikkel Ricky'
        description = ugettext_lazy('Accept card payments using Scandinavic payment provider Nets / DIBS. <span class="text-danger">Do not use this plugin for new integrations, it uses a deprecated API that will be disabled by Nets soon. Use the "nets Easy Payments" plugin instead.</span>')
        visible = True
        category = 'PAYMENT'
        version = '1.0.0'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_paymentdibs.PluginApp'
