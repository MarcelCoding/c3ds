import itertools
import random

from django import template

register = template.Library()


@register.filter(name='times')
def times(number):
    return range(number)


_logo_view_counter = itertools.count(1)


@register.simple_tag(name='logo_text')
def logo_text():
    """Return the logo text; every 10th render picks a funny typo."""
    count = next(_logo_view_counter)
    if count % 10 == 0:
        return random.choice(['Datensuren', 'Dasputenren', 'Datensputen'])
    return 'Datenspuren'
