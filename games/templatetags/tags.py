import re

from django import template
from django.conf import settings
from django.template import TemplateSyntaxError
from django.template.defaultfilters import stringfilter
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def current(context, pattern_or_urlname):
    try:
        pattern = "^" + reverse(pattern_or_urlname)
    except NoReverseMatch:
        pattern = pattern_or_urlname
    path = context["request"].path
    if re.search(pattern, path):
        return mark_safe("current")
    return ""


# pluralize for russian language
# {{someval|rupluralize:"товар,товара,товаров"}}
@register.filter(is_safe=False)
@stringfilter
def rupl(value, arg):
    bits = arg.split(",")
    try:
        one = str(value)[-1:]
        dec = str(value)[-2:-1]
        if dec == "1":
            res = bits[2]
        elif one == "1":
            res = bits[0]
        elif one in "234":
            res = bits[1]
        else:
            res = bits[2]
        return "%s %s" % (value, res)
    except:
        raise TemplateSyntaxError
    return ""


@register.simple_tag(takes_context=False)
def version():
    return settings.VERSION
