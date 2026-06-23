from datetime import date

from django.contrib.staticfiles import finders
from django.template import Context, Template

from releasewatch.models import DatePrecision


def render_template(source, context=None):
    return Template(source).render(Context(context or {}))


def test_base_template_has_skip_link_main_landmark_and_navigation(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="#main-content"' in html
    assert '<main id="main-content"' in html
    assert 'aria-label="Primary"' in html


def test_focus_visible_css_rule_exists():
    css = open("static/releasewatch/site.css", encoding="utf-8").read()

    assert ":focus-visible" in css
    assert "outline" in css
    assert "scroll-margin-top" in css


def test_site_css_is_discoverable_by_staticfiles():
    assert finders.find("releasewatch/site.css") is not None


def test_release_date_filter_formats_precision():
    html = render_template(
        "{% load releasewatch_ui %}"
        "{{ value|release_date:precision }}",
        {"value": date(2026, 6, 22), "precision": DatePrecision.DAY},
    )

    assert "June 22, 2026" in html


def test_release_date_filter_formats_month_precision():
    html = render_template(
        "{% load releasewatch_ui %}"
        "{{ value|release_date:precision }}",
        {"value": date(2026, 6, 1), "precision": DatePrecision.MONTH},
    )

    assert "June 2026" in html


def test_release_date_filter_formats_year_precision():
    html = render_template(
        "{% load releasewatch_ui %}"
        "{{ value|release_date:precision }}",
        {"value": date(2026, 1, 1), "precision": DatePrecision.YEAR},
    )

    assert "2026" in html
