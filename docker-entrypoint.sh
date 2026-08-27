#!/bin/sh
# Hand the mounted volume to the app user, then drop privileges.
#
# Railway, Fly and Docker all mount a volume owned by root, which replaces
# whatever the image had at that path. The app runs unprivileged -- it pushes
# user-supplied video through ffmpeg -- so without this it cannot create
# /app/storage/uploads and dies on the first import.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/storage/uploads /app/storage/renders /app/storage/cache
    # Only the mount point needs fixing; -R over a large media volume would
    # add minutes to every cold start.
    chown clipforge:clipforge /app/storage \
        /app/storage/uploads /app/storage/renders /app/storage/cache || true
    exec gosu clipforge "$@"
fi

# Already unprivileged (e.g. a platform that ignores USER): just run.
exec "$@"
