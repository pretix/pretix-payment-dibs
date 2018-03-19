from django import template

register = template.Library()

@register.filter
def dibs_amount(value):
    return int(value) / 100
