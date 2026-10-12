"""The search indexes on articles_article, for both databases we run on.

- MySQL 8 (development): the title gets an **ngram** FULLTEXT index (type-
  ahead, partial words, two-letter terms like "TB"), the article text a
  word-based one. Stopwords must be off while ngram indexes are built.
- MariaDB (the production server): there is no ngram parser, so the title
  gets a word-based index too. articles/search.py then matches title words
  by their beginning ("vacc*") and its plain-substring fallback covers what
  the indexes can't (two-letter terms, the middle of a word).

MariaDB can't roll back table changes, so a migration that failed half way
leaves some of its changes behind. Every step here checks first (column
there? index there?) and can safely run again.
"""

TABLE = 'articles_article'
TITLE_INDEX = 'articles_article_title_ngram'  # same name on MariaDB, where it's word-based
WORDS_INDEX = 'articles_article_search_words'
OLD_INDEXES = ('articles_article_fulltext', 'articles_article_search_ngram')


def is_mariadb(connection) -> bool:
    return connection.vendor == 'mysql' and connection.mysql_is_mariadb


def index_names(cursor) -> set[str]:
    cursor.execute(f'SHOW INDEX FROM {TABLE}')
    key_name = [col[0] for col in cursor.description].index('Key_name')
    return {row[key_name] for row in cursor.fetchall()}


def column_exists(connection, column: str) -> bool:
    with connection.cursor() as cursor:
        return column in {c.name for c in connection.introspection.get_table_description(cursor, TABLE)}


def add_title_index(cursor, connection, *, replace: bool = False) -> None:
    existing = index_names(cursor)
    if TITLE_INDEX in existing:
        if not replace:
            return
        cursor.execute(f'ALTER TABLE {TABLE} DROP INDEX {TITLE_INDEX}')
    if is_mariadb(connection):
        cursor.execute(f'ALTER TABLE {TABLE} ADD FULLTEXT INDEX {TITLE_INDEX} (title)')
    else:
        cursor.execute('SET SESSION innodb_ft_enable_stopword=OFF')
        cursor.execute(f'ALTER TABLE {TABLE} ADD FULLTEXT INDEX {TITLE_INDEX} (title) WITH PARSER ngram')


def add_words_index(cursor, *, replace: bool = False) -> None:
    existing = index_names(cursor)
    if WORDS_INDEX in existing:
        if not replace:
            return
        cursor.execute(f'ALTER TABLE {TABLE} DROP INDEX {WORDS_INDEX}')
    cursor.execute(f'ALTER TABLE {TABLE} ADD FULLTEXT INDEX {WORDS_INDEX} (search_text)')


def drop_indexes(cursor, names) -> None:
    existing = index_names(cursor)
    for name in names:
        if name in existing:
            cursor.execute(f'ALTER TABLE {TABLE} DROP INDEX {name}')


def setup(connection) -> None:
    """The final set of search indexes, whatever state the table is in."""
    if connection.vendor != 'mysql':
        return
    with connection.cursor() as cursor:
        drop_indexes(cursor, OLD_INDEXES)
        add_title_index(cursor, connection)
        add_words_index(cursor)
