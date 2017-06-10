import re

from django import template
from django.core.urlresolvers import reverse, NoReverseMatch
from django.utils.safestring import mark_safe
from django.template.defaultfilters import stringfilter
from django.template import TemplateSyntaxError

register = template.Library()


@register.simple_tag(takes_context=True)
def current(context, pattern_or_urlname):
    try:
        pattern = '^' + reverse(pattern_or_urlname)
    except NoReverseMatch:
        pattern = pattern_or_urlname
    path = context['request'].path
    if re.search(pattern, path):
        return mark_safe('current')
    return ''


# pluralize for russian language
# {{someval|rupluralize:"товар,товара,товаров"}}
@register.filter(is_safe=False)
@stringfilter
def rupl(value, arg):
    bits = arg.split(u',')
    try:
        one = str(value)[-1:]
        dec = str(value)[-2:-1]
        if dec == '1':
            res = bits[2]
        elif one == '1':
            res = bits[0]
        elif one in '234':
            res = bits[1]
        else:
            res = bits[2]
        return "%s %s" % (value, res)
    except:
        raise TemplateSyntaxError
    return ''
