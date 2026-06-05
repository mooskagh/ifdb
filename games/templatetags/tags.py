import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape

from django import template
from django.conf import settings
from django.template import TemplateSyntaxError
from django.template.defaultfilters import stringfilter
from django.urls import NoReverseMatch, reverse
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def costcell(value, decimals=4):
    """Decimal-aligned money cell: trailing zeros kept for alignment but
    hidden, negative/None (variable pricing) shown as an em dash."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        return mark_safe("—")
    if amount < 0:
        return mark_safe("—")
    text = f"{amount:.{int(decimals)}f}".replace(".", ",")
    head = text.rstrip("0").rstrip(",")
    tail = text[len(head) :]
    if not tail:
        return mark_safe(head)
    return format_html('{}<span class="zeros">{}</span>', head, tail)


@register.filter
def prettyjson(value):
    if isinstance(value, str):
        value = unescape(value)
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return mark_safe(conditional_escape(value))
    return mark_safe(
        conditional_escape(json.dumps(value, ensure_ascii=False, indent=2))
    )


@register.filter
def is_error_tool_result(message):
    if not isinstance(message, dict) or message.get("role") != "tool":
        return False
    try:
        content = json.loads(message.get("content") or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(content, dict) and content.get("status") == "error"


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
    except (IndexError, ValueError):
        raise TemplateSyntaxError
    return ""


@register.simple_tag(takes_context=True)
def has_perm(context, expr):
    return context["request"].perm(expr)


@register.simple_tag(takes_context=False)
def version():
    return settings.VERSION


@register.simple_tag
def safe_url(viewname, **kwargs):
    """
    Like {% url %} but returns empty string if the reverse lookup fails.
    Usage: {% safe_url 'show_competition' slug=x.slug doc='' as url %}
    """
    try:
        return reverse(viewname, kwargs=kwargs)
    except NoReverseMatch:
        return ""
