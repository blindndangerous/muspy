from config.celery import app


def test_celery_app_loads_django_settings():
    assert app.main == "config"
    assert app.conf.broker_url.startswith("amqp://")
    assert app.conf.task_ignore_result is True
    assert app.conf.task_default_queue == "maintenance"


def test_celery_routes_import_tasks_to_expected_queues():
    routes = app.conf.task_routes

    assert routes["releasewatch.tasks.run_import"]["queue"] == "imports"
    assert routes["releasewatch.tasks.import_provider_account"]["queue"] == "imports"
    assert routes["releasewatch.tasks.enqueue_due_provider_imports"]["queue"] == "maintenance"


def test_celery_uses_json_serialization_only():
    assert app.conf.task_serializer == "json"
    assert app.conf.accept_content == ["json"]
