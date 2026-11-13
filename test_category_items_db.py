"""PostgreSQL regression tests; set FORAGO_TEST_DATABASE_URL to an isolated database."""

import asyncio
import os
from pathlib import Path
import shutil
from uuid import uuid4

import asyncpg
import pytest

import queries


@pytest.mark.asyncio
async def test_user_items_have_separate_ids_and_visible_shared_items_are_reused(
    monkeypatch, tmp_path,
):
    database_url = os.environ.get("FORAGO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set FORAGO_TEST_DATABASE_URL to run PostgreSQL integration tests")

    schema = f"test_items_{uuid4().hex}"
    admin = await asyncpg.connect(database_url)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = None
    try:
        pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=5,
            server_settings={"search_path": schema},
        )
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE categories (
                    id uuid PRIMARY KEY, app_variant_id uuid NOT NULL,
                    parent_category_id uuid, slug text NOT NULL
                );
                CREATE TABLE app_variants (id uuid PRIMARY KEY, code text);
                CREATE TABLE profiles (
                    id uuid PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE category_translations (
                    category_id uuid NOT NULL, language_code text NOT NULL,
                    label text, PRIMARY KEY (category_id, language_code)
                );
                CREATE TABLE category_items (
                    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                    app_variant_id uuid NOT NULL, category_id uuid NOT NULL,
                    canonical_key text, created_by_user_id uuid NOT NULL,
                    owner_type text NOT NULL, visibility_state text NOT NULL,
                    approval_state text NOT NULL,
                    promoted_to_admin boolean NOT NULL DEFAULT false,
                    image_url text, created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE UNIQUE INDEX ux_category_items_category_canonical_key
                    ON category_items(category_id, canonical_key)
                    WHERE canonical_key IS NOT NULL;
                CREATE TABLE category_item_translations (
                    item_id uuid NOT NULL, language_code text NOT NULL,
                    title text NOT NULL, description_text text,
                    search_tsv tsvector,
                    PRIMARY KEY (item_id, language_code)
                );
                CREATE TABLE item_badges (id uuid PRIMARY KEY, code text);
                CREATE TABLE category_item_badges (
                    item_id uuid, badge_id uuid, assigned_by_user_id uuid,
                    PRIMARY KEY (item_id, badge_id)
                );
            """)
            variant, category, user_a, user_b = (uuid4() for _ in range(4))
            await conn.execute(
                "INSERT INTO app_variants(id, code) VALUES($1, 'forago-sk')",
                variant,
            )
            await conn.execute("INSERT INTO profiles(id) VALUES($1)", user_a)
            await conn.execute(
                "INSERT INTO categories(id, app_variant_id, slug) VALUES($1, $2, 'mushrooms')",
                category, variant,
            )
            legacy_id = await conn.fetchval(
                """
                INSERT INTO category_items(
                    app_variant_id, category_id, canonical_key, created_by_user_id,
                    owner_type, visibility_state, approval_state
                ) VALUES($1, $2, 'legacy', $3, 'user', 'visible', 'none')
                RETURNING id
                """,
                variant, category, user_a,
            )
            migration = (
                Path(__file__).parent
                / "migrations"
                / "023_scope_category_item_uniqueness.sql"
            ).read_text(encoding="utf-8")
            await conn.execute(migration)
            await conn.execute(migration)
            assert await conn.fetchval(
                "SELECT id FROM category_items WHERE id=$1", legacy_id
            ) == legacy_id

        async def acquire():
            return await pool.acquire()

        async def release(conn):
            await pool.release(conn)

        monkeypatch.setattr(queries, "get_db_connection", acquire)
        monkeypatch.setattr(queries, "release_db_connection", release)

        async def create(user, title):
            return await queries.create_category_item(
                user_id=str(user), app_variant_id=str(variant),
                language_code="sk", top_category_slug="mushrooms",
                category_slug="mushrooms", title=title,
            )

        first = await create(user_a, "Huba vlastna")
        second = await create(user_b, "Huba vlastna")
        assert first["id"] != second["id"]
        assert first["createdByUserId"] == str(user_a)
        assert second["createdByUserId"] == str(user_b)
        assert (await create(user_b, "Huba vlastna"))["id"] == second["id"]

        concurrent = await asyncio.gather(
            *[create(user_a, "Nova spolocna") for _ in range(4)]
        )
        assert len({item["id"] for item in concurrent}) == 1

        async with pool.acquire() as conn:
            admin_id = await conn.fetchval(
                """
                INSERT INTO category_items(
                    app_variant_id, category_id, canonical_key, created_by_user_id,
                    owner_type, visibility_state, approval_state
                ) VALUES($1, $2, 'official', $3, 'admin', 'visible', 'approved')
                RETURNING id
                """,
                variant, category, user_a,
            )
        assert (await create(user_b, "Official"))["id"] == str(admin_id)

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE category_items SET approval_state='approved' WHERE id=$1::uuid",
                first["id"],
            )
        assert (await create(user_b, "Huba vlastna"))["id"] == second["id"]
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE category_items SET approval_state='none' WHERE id=$1::uuid",
                first["id"],
            )

        visible_a = await queries.list_category_items(
            str(user_a), str(variant), "sk"
        )
        visible_b = await queries.list_category_items(
            str(user_b), str(variant), "sk"
        )
        assert first["id"] in {item["id"] for item in visible_a}
        assert first["id"] not in {item["id"] for item in visible_b}
        assert second["id"] in {item["id"] for item in visible_b}
        assert second["id"] not in {item["id"] for item in visible_a}
        assert str(admin_id) in {item["id"] for item in visible_a}
        assert str(admin_id) in {item["id"] for item in visible_b}

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE category_items SET visibility_state='hidden' WHERE id=$1::uuid",
                first["id"],
            )
        with pytest.raises(ValueError, match="category_item_error_duplicate_inaccessible"):
            await create(user_a, "Huba vlastna")
        with pytest.raises(ValueError, match="category_item_error_invalid_category"):
            await queries.create_category_item(
                str(user_a), str(variant), "sk", "missing", "missing", "Missing"
            )

        psql = shutil.which("psql")
        if psql is None:
            pytest.fail("psql is required to verify the CSV imports")
        csv_path = tmp_path / "items.csv"
        csv_path.write_text(
            "Slovensky,Latinsky,Cesky,Typ,Mesiace\n"
            "Official name,Huba vlastna,Official name,,\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PGOPTIONS"] = f"-c search_path={schema}"
        for script in ("import_category_items_from_csv.sql", "import_mushrooms_from_csv.sql"):
            for _ in range(2):
                process = await asyncio.create_subprocess_exec(
                    psql, "-X", "-v", "ON_ERROR_STOP=1",
                    "-v", f"csv_path={csv_path.as_posix()}",
                    "-v", "category_slug=mushrooms", "-d", database_url,
                    "-f", str(Path(__file__).parent / "scripts" / script),
                    env=env, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await process.communicate()
                assert process.returncode == 0, stderr.decode(errors="replace")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ci.id, ci.owner_type, cit.title
                FROM category_items ci
                LEFT JOIN category_item_translations cit
                    ON cit.item_id=ci.id AND cit.language_code='sk'
                WHERE ci.category_id=$1 AND ci.canonical_key='huba-vlastna'
                ORDER BY ci.owner_type, ci.id
                """,
                category,
            )
        assert len(rows) == 3
        assert [row["owner_type"] for row in rows].count("admin") == 1
        assert {row["title"] for row in rows if row["owner_type"] == "user"} == {
            "Huba vlastna"
        }
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
