"""
Celery application instance for the SDUI project.

Import this in tasks using:
    from config.celery import app as celery_app
or rely on the shared_task decorator which autodiscovers it.
"""

import os

from celery import Celery

# Point Celery at Django's settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("sdui")

# Load Celery config from Django settings, namespace CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks from all INSTALLED_APPS
app.autodiscover_tasks()
