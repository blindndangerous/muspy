import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command


def test_env_example_documents_django_superuser_variables():
    env_example = ".env.example"
    contents = open(env_example, encoding="utf-8").read()

    assert "DJANGO_SUPERUSER_USERNAME=" in contents
    assert "DJANGO_SUPERUSER_EMAIL=" in contents
    assert "DJANGO_SUPERUSER_PASSWORD=" in contents
    assert "DEV_ADMIN_" not in contents


@pytest.mark.django_db
def test_ensure_dev_admin_refuses_when_debug_false_without_override(monkeypatch, settings):
    settings.DEBUG = False
    monkeypatch.delenv("ALLOW_DEV_ADMIN_BOOTSTRAP", raising=False)
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "secret-pass")

    with pytest.raises(CommandError, match="refuses to run"):
        call_command("ensure_dev_admin")

    assert not get_user_model().objects.filter(username="admin").exists()


@pytest.mark.parametrize("allow_value", ["0", "false", "random", " yes "])
@pytest.mark.django_db
def test_ensure_dev_admin_refuses_falseish_override_values(monkeypatch, settings, allow_value):
    settings.DEBUG = False
    monkeypatch.setenv("ALLOW_DEV_ADMIN_BOOTSTRAP", allow_value)
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "secret-pass")

    with pytest.raises(CommandError, match="refuses to run"):
        call_command("ensure_dev_admin")

    assert not get_user_model().objects.filter(username="admin").exists()


@pytest.mark.django_db
def test_ensure_dev_admin_requires_password_when_allowed(monkeypatch, settings):
    settings.DEBUG = True
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="DJANGO_SUPERUSER_PASSWORD is required"):
        call_command("ensure_dev_admin")

    assert not get_user_model().objects.filter(username="admin").exists()


@pytest.mark.django_db
def test_ensure_dev_admin_creates_superuser_from_env(monkeypatch, settings, capsys):
    settings.DEBUG = True
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "devadmin")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "devadmin@example.test")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "initial-pass")

    call_command("ensure_dev_admin")

    user = get_user_model().objects.get(username="devadmin")
    assert user.email == "devadmin@example.test"
    assert user.is_active
    assert user.is_staff
    assert user.is_superuser
    assert user.check_password("initial-pass")
    assert "dev admin" in capsys.readouterr().out.lower()


@pytest.mark.django_db
def test_ensure_dev_admin_updates_existing_user_idempotently(monkeypatch, settings):
    settings.DEBUG = False
    monkeypatch.setenv("ALLOW_DEV_ADMIN_BOOTSTRAP", "yes")
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "sameadmin")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "first@example.test")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "first-pass")

    call_command("ensure_dev_admin")
    user_model = get_user_model()
    user = user_model.objects.get(username="sameadmin")
    user_id = user.pk

    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "second@example.test")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "second-pass")
    call_command("ensure_dev_admin")

    user = user_model.objects.get(username="sameadmin")
    assert user.pk == user_id
    assert user_model.objects.filter(username="sameadmin").count() == 1
    assert user.email == "second@example.test"
    assert user.is_active
    assert user.is_staff
    assert user.is_superuser
    assert user.check_password("second-pass")
