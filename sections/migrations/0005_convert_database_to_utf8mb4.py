# Converts the database default charset and every table that isn't already
# utf8mb4 to utf8mb4. Written after Nepali (Devanagari) section names showed
# up as "??" in the menubar on the cPanel host: that database had been
# created with a latin1 default, so MySQL silently replaced every
# non-latin1 character with "?" on save. OPTIONS['charset'] = 'utf8mb4' in
# settings.py only fixes the *connection* — it can't widen a latin1 column.
#
# Lives in `sections` only because that's where the symptom surfaced; it
# acts on the whole database, not just this app's tables. After the
# ALTER DATABASE, tables created later (by future migrations or
# createcachetable in deploy.sh) inherit utf8mb4 as the default.
#
# Idempotent and a no-op where everything is already utf8mb4 (e.g. a local
# MySQL 8 dev database). Skipped entirely on non-MySQL backends.
#
# NOTE: this can't recover text that was already saved as "?" — the original
# characters were discarded at write time. Re-enter those values in the admin
# after this runs.
from django.db import migrations

# utf8mb4_0900_ai_ci exists only on MySQL 8+, not MariaDB (common on
# cPanel/WHM hosts); utf8mb4_unicode_ci works on both.
FALLBACK_COLLATION = 'utf8mb4_unicode_ci'


def convert_to_utf8mb4(apps, schema_editor) -> None:
    """Convert the database default and all non-utf8mb4 tables to utf8mb4."""
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return

    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE(), @@collation_database')
        db_name, db_collation = cursor.fetchone()

        # Keep an existing utf8mb4 collation (so a utf8mb4_0900_ai_ci dev DB
        # doesn't end up with mixed collations across tables); otherwise use
        # the portable fallback.
        collation = db_collation if db_collation.startswith('utf8mb4') else FALLBACK_COLLATION

        if not db_collation.startswith('utf8mb4'):
            cursor.execute(
                f'ALTER DATABASE `{db_name}` CHARACTER SET utf8mb4 COLLATE {collation}'
            )

        # A table needs converting if its default collation isn't utf8mb4
        # or any of its text columns aren't.
        cursor.execute(
            """
            SELECT TABLE_NAME FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
              AND TABLE_COLLATION NOT LIKE 'utf8mb4%%'
            UNION
            SELECT TABLE_NAME FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND CHARACTER_SET_NAME IS NOT NULL
              AND CHARACTER_SET_NAME <> 'utf8mb4'
            """,
            [db_name, db_name],
        )
        tables = sorted(row[0] for row in cursor.fetchall())
        if not tables:
            return

        # FK columns must share a charset with the column they reference;
        # converting tables one at a time would briefly break that, which
        # MySQL refuses unless FK checks are off for the session.
        errors: list[str] = []
        cursor.execute('SET FOREIGN_KEY_CHECKS = 0')
        try:
            for table in tables:
                try:
                    cursor.execute(
                        f'ALTER TABLE `{table}` CONVERT TO CHARACTER SET utf8mb4 COLLATE {collation}'
                    )
                except Exception as exc:  # noqa: BLE001 — collect and report all failures at once
                    errors.append(f'{table}: {exc}')
        finally:
            cursor.execute('SET FOREIGN_KEY_CHECKS = 1')

    if errors:
        # MySQL DDL isn't transactional, so tables that converted stay
        # converted; failing here leaves the migration unapplied so a re-run
        # (after fixing the cause) picks up only the remaining tables.
        raise RuntimeError('utf8mb4 conversion failed for:\n' + '\n'.join(errors))


class Migration(migrations.Migration):
    """Database-wide utf8mb4 conversion (see module comment)."""

    dependencies = [
        ('sections', '0004_topic_digest_schedule'),
    ]

    operations = [
        migrations.RunPython(convert_to_utf8mb4, migrations.RunPython.noop),
    ]
