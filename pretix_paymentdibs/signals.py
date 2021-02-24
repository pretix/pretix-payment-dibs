import json

from django.dispatch import receiver
from pretix.base.signals import register_payment_providers, logentry_display
from django.utils.translation import gettext as _

@receiver(register_payment_providers, dispatch_uid="payment_dibs")
def register_payment_provider(sender, **kwargs):
    from .payment import DIBS
    return DIBS


@receiver(signal=logentry_display, dispatch_uid="payment_dibs_logentry_display")
def pretixcontrol_logentry_display(sender, logentry, **kwargs):
    if logentry.action_type != 'pretix_paymentdibs.callback':
        return

    data = logentry.parsed_data
    return _('DIBS reported a status code: {}').format(data['statuscode'])
