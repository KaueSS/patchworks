"""Isolated SQLite settings for the automated Django test suite."""

from patchworks.settings import *  # noqa: F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
}
