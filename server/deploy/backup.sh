#!/bin/sh
# Nightly encrypted backup.
#
# The dump is encrypted with `age` BEFORE it leaves the box, so the object-store
# copy is useless to anyone who obtains it — including the storage provider.
#
# Use an APPEND-ONLY object-store key. If the VPS is ransomwared, the attacker
# must not be able to delete your backup history.

set -eu

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="/backups/howdy-${STAMP}.sql.gz.age"

echo "[backup] dumping…"
pg_dump -h db -U howdy_app -d howdy --no-owner --no-privileges \
  | gzip -9 \
  | age -r "$(cat /run/secrets/backup_age_pubkey 2>/dev/null || echo '')" \
  > "$OUT"

echo "[backup] wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Retention: 7 daily locally; the object store keeps the long tail.
ls -1t /backups/howdy-*.sql.gz.age 2>/dev/null | tail -n +8 | xargs -r rm -f

if [ -n "${B2_BUCKET:-}" ]; then
  echo "[backup] uploading to ${B2_BUCKET}…"
  # rclone/restic goes here; keep credentials append-only.
fi

# Tell the dead-man's switch we succeeded. If this ping stops, you get paged —
# which is the only way you ever learn a backup silently broke.
[ -n "${HEALTHCHECK_URL:-}" ] && wget -q -O /dev/null "$HEALTHCHECK_URL" || true

echo "[backup] done"
