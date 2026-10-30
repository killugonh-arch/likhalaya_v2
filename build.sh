#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
python manage.py createcachetable
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
python manage.py ensure_admin