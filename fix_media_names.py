"""
fix_media_names.py  -  find (and optionally repair) image/video records whose
saved file name no longer matches the file that is really in Cloudinary.

Put this file next to manage.py, then run in PowerShell (same window where the
CLOUDINARY_* variables are set):

    python fix_media_names.py            # DRY RUN: only reports, changes nothing
    python fix_media_names.py --apply    # repoints records that have exactly one match

It only changes the database you run it against (your local db.sqlite3 unless
DATABASE_URL is set). It never prints your Cloudinary keys.
"""
import os
import re
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "likhalaya_project.settings")

import django  # noqa: E402

django.setup()

import cloudinary.api  # noqa: E402
import requests  # noqa: E402
from django.apps import apps  # noqa: E402
from django.db import models  # noqa: E402

APPLY = "--apply" in sys.argv
SUFFIX = re.compile(r"_[A-Za-z0-9]{6,7}$")  # random ending added to duplicate names


def strip_media(path):
    path = path.replace("\\", "/")
    return path[len("media/"):] if path.startswith("media/") else path


def normalize(path):
    """'media/gcash_qr/gcash-qr_MyRaB1M.jpg' -> 'gcash_qr/gcash-qr'"""
    path = strip_media(path)
    folder, _, filename = path.rpartition("/")
    base = os.path.splitext(filename)[0]
    base = SUFFIX.sub("", base)
    return f"{folder}/{base}" if folder else base


def load_cloudinary_resources():
    found = []
    for rtype in ("image", "video"):
        cursor = None
        while True:
            kwargs = dict(resource_type=rtype, type="upload", max_results=500)
            if cursor:
                kwargs["next_cursor"] = cursor
            res = cloudinary.api.resources(**kwargs)
            for r in res.get("resources", []):
                found.append({
                    "public_id": r["public_id"],
                    "format": r.get("format", ""),
                    "type": rtype,
                    "key": normalize(r["public_id"]),
                })
            cursor = res.get("next_cursor")
            if not cursor:
                break
    return found


def url_ok(url):
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        return r.status_code == 200, r.status_code
    except requests.RequestException as exc:
        return False, type(exc).__name__


def main():
    print("Loading file list from Cloudinary ...")
    resources = load_cloudinary_resources()
    by_key = {}
    for r in resources:
        by_key.setdefault(r["key"], []).append(r)
    print(f"Cloudinary has {len(resources)} files.\n")

    checked = broken = fixable = fixed = 0
    for model in apps.get_models():
        file_fields = [f for f in model._meta.get_fields() if isinstance(f, models.FileField)]
        if not file_fields:
            continue
        for obj in model._base_manager.all():  # _base_manager includes archived rows
            for field in file_fields:
                value = getattr(obj, field.name)
                if not value:
                    continue
                try:
                    url = value.url
                except Exception as exc:  # noqa: BLE001
                    print(f"[?] {model.__name__} #{obj.pk} {field.name}: cannot build url ({exc})")
                    continue
                if url.startswith("/"):
                    continue  # local /media/ path, not a Cloudinary link
                checked += 1
                ok, status = url_ok(url)
                if ok:
                    continue
                broken += 1
                label = f"{model.__name__} #{obj.pk} {field.name}  name='{value.name}'  (HTTP {status})"
                matches = by_key.get(normalize(value.name), [])
                if len(matches) == 1:
                    m = matches[0]
                    new_name = m["public_id"] + ("." + m["format"] if m["format"] else "")
                    fixable += 1
                    print(f"[BROKEN] {label}\n         -> match found: {new_name}")
                    if APPLY:
                        setattr(obj, field.name, new_name)
                        obj.save(update_fields=[field.name])
                        fixed += 1
                        print("         -> repointed")
                elif len(matches) > 1:
                    print(f"[BROKEN] {label}\n         -> {len(matches)} possible matches, not touching it:")
                    for m in matches:
                        print(f"            {m['public_id']}")
                else:
                    print(f"[BROKEN] {label}\n         -> no matching file in Cloudinary, re-upload this one")

    print(f"\nChecked {checked} files, {broken} broken, {fixable} can be repointed.")
    if APPLY:
        print(f"Repointed {fixed} records.")
    elif fixable:
        print("Dry run only. Run again with --apply to repoint them.")


if __name__ == "__main__":
    main()