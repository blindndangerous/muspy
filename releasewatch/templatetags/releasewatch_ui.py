from django import template

from releasewatch.models import DatePrecision

register = template.Library()


@register.filter
def release_date(value, precision):
    if value is None:
        return "Unknown date"
    if precision == DatePrecision.YEAR:
        return str(value.year)
    if precision == DatePrecision.MONTH:
        return value.strftime("%B %Y")
    return f"{value.strftime('%B')} {value.day}, {value.year}"
