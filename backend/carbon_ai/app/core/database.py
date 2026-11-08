from collections.abc import Generator
from datetime import date
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

if not settings.database_url.startswith("mysql"):
    raise RuntimeError(
        "SQLite backend has been removed. Please configure MySQL via DATABASE_URL or DB_BACKEND=mysql."
    )

engine_kwargs = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_factor_library(db: Session) -> None:
    from app.models.factor_library import FactorLibrary

    existing = db.query(FactorLibrary).count()
    if existing > 0:
        return

    factors = [
        # ======================
        # 公共机构 4 大标准排放源（完全对齐 JS/T 303—2026）
        # ======================
        FactorLibrary(
            name="外购电力",
            category="外购电力",
            industry="公共机构",
            region="全国",
            value=0.5703,
            unit="tCO2e/MWh",
            source="JS/T 303—2026 表A.2 全国平均",
            effective_date=date(2026, 4, 1),
            expiry_date=None,
            priority=1,
        ),
        FactorLibrary(
            name="汽油",
            category="汽油",
            industry="公共机构",
            region="全国",
            value=2.179,
            unit="kgCO2e/L",
            source="JS/T 303—2026 表A.1",
            effective_date=date(2026, 4, 1),
            expiry_date=None,
            priority=1,
        ),
        FactorLibrary(
            name="柴油",
            category="柴油",
            industry="公共机构",
            region="全国",
            value=2.718,
            unit="kgCO2e/L",
            source="JS/T 303—2026 表A.1",
            effective_date=date(2026, 4, 1),
            expiry_date=None,
            priority=1,
        ),
        FactorLibrary(
            name="外购热力",
            category="外购热力",
            industry="公共机构",
            region="全国",
            value=0.11,
            unit="tCO2e/GJ",
            source="JS/T 303—2026 第8章",
            effective_date=date(2026, 4, 1),
            expiry_date=None,
            priority=1,
        ),
    ]
    db.add_all(factors)
    db.commit()


def _ensure_public_institution_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    required_columns = {
        "projects": {
            "calculation_profile": "VARCHAR(32) NOT NULL DEFAULT 'AUTO'",
            "is_deleted": "BOOLEAN NOT NULL DEFAULT 0",
            "deleted_at": "DATETIME",
            "period_start": "DATE",
            "period_end": "DATE",
        },
        "emission_sources": {
            "emission_class": "VARCHAR(16) NOT NULL DEFAULT 'direct'",
            "ghg_category": "VARCHAR(64) NOT NULL DEFAULT ''",
            "energy_type": "VARCHAR(16) NOT NULL DEFAULT 'fuel'",
            "consumption_type": "VARCHAR(16) NOT NULL DEFAULT 'purchased'",
            "is_green_electricity": "BOOLEAN NOT NULL DEFAULT 0",
            "gas": "VARCHAR(32) NOT NULL DEFAULT 'CO2'",
            "iso_category_major": "INTEGER NOT NULL DEFAULT 1",
            "iso_category_code": "VARCHAR(16) NOT NULL DEFAULT '1.1'",
            "is_removal": "BOOLEAN NOT NULL DEFAULT 0",
            "is_storage": "BOOLEAN NOT NULL DEFAULT 0",
            "period_start": "DATE",
            "period_end": "DATE",
        },
        "factor_library": {
            "emission_class": "VARCHAR(16) NOT NULL DEFAULT 'direct'",
            "energy_type": "VARCHAR(16) NOT NULL DEFAULT 'fuel'",
            "consumption_type": "VARCHAR(16) NOT NULL DEFAULT 'purchased'",
            "gas": "VARCHAR(32) NOT NULL DEFAULT 'CO2'",
            "standard_code": "VARCHAR(64) NOT NULL DEFAULT 'JS/T 303-2026'",
        },
        "uncertainty_assessments": {
            "emission_source_name": "VARCHAR(255) NOT NULL DEFAULT ''",
            "facility": "VARCHAR(255) NOT NULL DEFAULT ''",
            "emission_amount": "FLOAT NOT NULL DEFAULT 0",
        },
    }

    with engine.begin() as conn:
        for table_name, columns in required_columns.items():
            table_info = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
            existing_columns = {row[1] for row in table_info}
            for column_name, column_definition in columns.items():
                if column_name not in existing_columns:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
                    )
        conn.exec_driver_sql(
            """
            UPDATE projects
            SET calculation_profile = CASE
                WHEN lower(standard) LIKE '%iso%14064%' THEN 'ISO14064'
                WHEN lower(standard) LIKE '%js/t%' OR standard LIKE '%303%' OR standard LIKE '%公共机构%' THEN 'JS_T303'
                ELSE calculation_profile
            END
            WHERE calculation_profile = 'AUTO'
            """
        )

        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET emission_class = CASE
                WHEN scope = 2 THEN 'indirect'
                ELSE emission_class
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET energy_type = 'electricity'
            WHERE category LIKE '%电%' OR name LIKE '%电%'
               OR lower(category) LIKE '%electric%' OR lower(name) LIKE '%electric%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET energy_type = 'heat'
            WHERE category LIKE '%热%' OR name LIKE '%热%'
               OR lower(category) LIKE '%heat%' OR lower(name) LIKE '%heat%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET consumption_type = 'transferred'
            WHERE category LIKE '%转供%' OR name LIKE '%转供%'
               OR lower(category) LIKE '%transfer%' OR lower(name) LIKE '%transfer%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET is_green_electricity = 1
            WHERE category LIKE '%绿电%' OR name LIKE '%绿电%'
               OR lower(category) LIKE '%green%' OR lower(name) LIKE '%green%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET gas = 'CO2'
            WHERE gas IS NULL OR gas = ''
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET scope = CASE
                WHEN emission_class = 'direct' THEN 1
                WHEN iso_category_major = 2 THEN 2
                ELSE 3
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET iso_category_major = CASE
                WHEN emission_class = 'direct' THEN 1
                WHEN energy_type IN ('electricity', 'heat') THEN 2
                ELSE 3
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET iso_category_code = CASE
                WHEN emission_class = 'direct'
                  AND (
                    category LIKE '%车%' OR name LIKE '%车%'
                    OR lower(category) LIKE '%vehicle%' OR lower(name) LIKE '%vehicle%'
                    OR lower(category) LIKE '%fleet%' OR lower(name) LIKE '%fleet%'
                    OR lower(category) LIKE '%transport%' OR lower(name) LIKE '%transport%'
                  )
                  THEN '1.3'
                WHEN emission_class = 'direct'
                  AND (
                    category LIKE '%工艺%' OR name LIKE '%工艺%'
                    OR lower(category) LIKE '%process%' OR lower(name) LIKE '%process%'
                  )
                  THEN '1.2'
                WHEN emission_class = 'direct'
                  AND (
                    category LIKE '%空调%' OR name LIKE '%空调%'
                    OR category LIKE '%冰箱%' OR name LIKE '%冰箱%'
                    OR category LIKE '%灭火器%' OR name LIKE '%灭火器%'
                    OR category LIKE '%化粪池%' OR name LIKE '%化粪池%'
                    OR category LIKE '%冷媒%' OR name LIKE '%冷媒%'
                    OR category LIKE '%制冷剂%' OR name LIKE '%制冷剂%'
                    OR lower(category) LIKE '%wd-40%' OR lower(name) LIKE '%wd-40%'
                    OR lower(category) LIKE '%fugitive%' OR lower(name) LIKE '%fugitive%'
                    OR lower(category) LIKE '%refrigerant%' OR lower(name) LIKE '%refrigerant%'
                  )
                  THEN '1.4'
                WHEN emission_class = 'direct'
                  AND (
                    category LIKE '%生物质%' OR name LIKE '%生物质%'
                    OR lower(category) LIKE '%biomass%' OR lower(name) LIKE '%biomass%'
                  )
                  THEN '1.5'
                WHEN emission_class = 'direct' THEN '1.1'
                WHEN emission_class = 'indirect' AND energy_type = 'electricity' THEN '2.1'
                WHEN emission_class = 'indirect' AND energy_type = 'heat' THEN '2.2'
                ELSE '3.1'
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE emission_sources
            SET ghg_category = CASE
                WHEN iso_category_major = 1 AND iso_category_code = '1.1' THEN '1.1固定燃烧'
                WHEN iso_category_major = 1 AND iso_category_code = '1.2' THEN '1.2工艺排放'
                WHEN iso_category_major = 1 AND iso_category_code = '1.3' THEN '1.3移动燃烧'
                WHEN iso_category_major = 1 AND iso_category_code = '1.4' THEN '1.4无组织排放'
                WHEN iso_category_major = 1 AND iso_category_code = '1.5' THEN '1.5生物质燃烧'
                WHEN iso_category_major = 2 AND iso_category_code = '2.1' THEN '2.1电力产生的间接排放'
                WHEN iso_category_major = 2 AND iso_category_code = '2.2' THEN '2.2热力产生的间接排放'
                ELSE COALESCE(NULLIF(ghg_category, ''), '3.1其他间接排放')
            END
            WHERE ghg_category IS NULL OR ghg_category = ''
            """
        )

        conn.exec_driver_sql(
            """
            UPDATE factor_library
            SET emission_class = 'indirect',
                energy_type = 'electricity'
            WHERE category LIKE '%电%' OR name LIKE '%电%'
               OR lower(category) LIKE '%electric%' OR lower(name) LIKE '%electric%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE factor_library
            SET emission_class = 'indirect',
                energy_type = 'heat'
            WHERE category LIKE '%热%' OR name LIKE '%热%'
               OR lower(category) LIKE '%heat%' OR lower(name) LIKE '%heat%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE factor_library
            SET consumption_type = 'transferred'
            WHERE category LIKE '%转供%' OR name LIKE '%转供%'
               OR lower(category) LIKE '%transfer%' OR lower(name) LIKE '%transfer%'
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE factor_library
            SET gas = 'CO2'
            WHERE gas IS NULL OR gas = ''
            """
        )

        source_columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(emission_sources)").fetchall()
        }
        sqlite_version = str(conn.exec_driver_sql("SELECT sqlite_version()").scalar_one())
        version_parts = tuple(int(part) for part in sqlite_version.split(".")[:3])
        has_legacy_quality_columns = (
            "data_quality_activity_level" in source_columns
            and "data_quality_factor_level" in source_columns
        )
        if has_legacy_quality_columns:
            conn.exec_driver_sql(
                """
                INSERT INTO uncertainty_assessments (
                    source_id,
                    activity_data_category,
                    factor_category,
                    activity_level,
                    factor_level,
                    average_score,
                    notes,
                    created_at,
                    updated_at
                )
                SELECT
                    es.id,
                    'legacy',
                    'legacy',
                    es.data_quality_activity_level,
                    es.data_quality_factor_level,
                    (es.data_quality_activity_level + es.data_quality_factor_level) / 2.0,
                    'Migrated from legacy emission_sources quality fields',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM emission_sources es
                LEFT JOIN uncertainty_assessments ua ON ua.source_id = es.id
                WHERE ua.id IS NULL
                  AND (es.data_quality_activity_level IS NOT NULL
                    OR es.data_quality_factor_level IS NOT NULL)
                """
            )

            if version_parts >= (3, 35, 0):
                conn.exec_driver_sql("ALTER TABLE emission_sources DROP COLUMN data_quality_activity_level")
                conn.exec_driver_sql("ALTER TABLE emission_sources DROP COLUMN data_quality_factor_level")

        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET activity_data_category = CASE
                WHEN lower(activity_data_category) IN ('continuous', 'continuous_monitoring', 'online_monitoring') THEN '自动连续监测'
                WHEN lower(activity_data_category) IN ('meter_reading', 'metering', 'nameplate', 'manual') THEN '定期量测/抄表/铭牌'
                WHEN lower(activity_data_category) IN ('estimate', 'manual_estimation') THEN '自行推估'
                WHEN activity_data_category IN ('抄表记录', '定期量测', '铭牌') THEN '定期量测/抄表/铭牌'
                WHEN activity_data_category = '推估' THEN '自行推估'
                ELSE activity_data_category
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET factor_category = CASE
                WHEN lower(factor_category) IN ('international', 'international_factor') THEN '国际排放因子'
                WHEN lower(factor_category) IN ('national', 'national_factor', 'national_default') THEN '国家排放因子'
                WHEN lower(factor_category) IN ('regional', 'regional_factor', 'regional_default') THEN '区域排放因子'
                WHEN factor_category = '国际' THEN '国际排放因子'
                WHEN factor_category = '国家' THEN '国家排放因子'
                WHEN factor_category = '区域' THEN '区域排放因子'
                ELSE factor_category
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET activity_level = CASE activity_data_category
                WHEN '自动连续监测' THEN 6
                WHEN '定期量测/抄表/铭牌' THEN 3
                WHEN '自行推估' THEN 1
                ELSE activity_level
            END,
            factor_level = CASE factor_category
                WHEN '国际排放因子' THEN 1
                WHEN '国家排放因子' THEN 2
                WHEN '区域排放因子' THEN 3
                ELSE factor_level
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET average_score = (COALESCE(activity_level, 0) + COALESCE(factor_level, 0)) / 2.0
            WHERE activity_level IS NOT NULL AND factor_level IS NOT NULL
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET emission_source_name = COALESCE(NULLIF(emission_source_name, ''), (
                    SELECT es.category
                    FROM emission_sources es
                    WHERE es.id = uncertainty_assessments.source_id
                )),
                facility = COALESCE(NULLIF(facility, ''), (
                    SELECT es.name
                    FROM emission_sources es
                    WHERE es.id = uncertainty_assessments.source_id
                )),
                emission_amount = COALESCE((
                    SELECT es.co2e
                    FROM emission_sources es
                    WHERE es.id = uncertainty_assessments.source_id
                ), 0.0)
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET emission_share = CASE
                WHEN (
                    SELECT SUM(es2.co2e)
                    FROM emission_sources es2
                    WHERE es2.project_id = (
                        SELECT es1.project_id
                        FROM emission_sources es1
                        WHERE es1.id = uncertainty_assessments.source_id
                    )
                ) > 0
                THEN emission_amount / (
                    SELECT SUM(es2.co2e)
                    FROM emission_sources es2
                    WHERE es2.project_id = (
                        SELECT es1.project_id
                        FROM emission_sources es1
                        WHERE es1.id = uncertainty_assessments.source_id
                    )
                )
                ELSE 0
            END
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE uncertainty_assessments
            SET weighted_score = COALESCE(average_score, 0) * COALESCE(emission_share, 0)
            """
        )

        table_names = {
            row[0]
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "emission_source_gases" in table_names:
            conn.exec_driver_sql(
                """
                UPDATE emission_sources
                SET gas = COALESCE((
                        SELECT esg.gas
                        FROM emission_source_gases esg
                        WHERE esg.source_id = emission_sources.id
                        ORDER BY esg.id ASC
                        LIMIT 1
                    ), gas),
                    gwp = COALESCE((
                        SELECT esg.gwp
                        FROM emission_source_gases esg
                        WHERE esg.source_id = emission_sources.id
                        ORDER BY esg.id ASC
                        LIMIT 1
                    ), gwp)
                """
            )
            conn.exec_driver_sql("DROP TABLE IF EXISTS emission_source_gases")


def _seed_quick_questions(db: Session) -> None:
    from app.models.quick_question import QuickQuestion

    existing = db.query(QuickQuestion).count()
    if existing > 0:
        return

    questions = [
        QuickQuestion(question="ISO 14064 和 JS/T 303 的区别是什么？", category="核算标准", sort_order=1),
        QuickQuestion(question="Scope 1/2/3 的定义和区别？", category="基础概念", sort_order=2),
        QuickQuestion(question="CBAM 申报需要准备哪些材料？", category="CBAM", sort_order=3),
        QuickQuestion(question="企业如何界定碳盘查的组织边界？", category="核算标准", sort_order=4),
        QuickQuestion(question="碳市场配额如何分配？履约成本怎么优化？", category="碳市场", sort_order=5),
        QuickQuestion(question="外购电力的排放因子如何选择？", category="排放因子", sort_order=6),
        QuickQuestion(question="不确定性评估的方法和流程是什么？", category="数据质量", sort_order=7),
        QuickQuestion(question="绿电对碳排放核算有什么影响？", category="绿电", sort_order=8),
        QuickQuestion(question="我的项目排放数据是多少？", category="业务查询", sort_order=9),
        QuickQuestion(question="哪些排放源占比最高？", category="业务查询", sort_order=10),
    ]
    db.add_all(questions)
    db.commit()


def _ensure_chat_history_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("chat_history"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("chat_history")}

    if settings.database_url.startswith("sqlite"):
        required = {
            "mode": "VARCHAR(32) NOT NULL DEFAULT 'rag'",
            "project_id": "INTEGER",
            "chart": "TEXT",
        }
    else:
        required = {
            "mode": "VARCHAR(32) NOT NULL DEFAULT 'rag'",
            "project_id": "INTEGER NULL",
            "chart": "TEXT NULL",
        }

    with engine.begin() as conn:
        for column_name, definition in required.items():
            if column_name in existing_columns:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE chat_history ADD COLUMN {column_name} {definition}"
            )


def _ensure_chat_session_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("chat_sessions"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("chat_sessions")}
    if settings.database_url.startswith("sqlite"):
        required = {
            "intake_form_json": "TEXT",
        }
    else:
        required = {
            "intake_form_json": "TEXT NULL",
        }

    with engine.begin() as conn:
        for column_name, definition in required.items():
            if column_name in existing_columns:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE chat_sessions ADD COLUMN {column_name} {definition}"
            )


def _ensure_knowledge_document_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("knowledge_documents"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("knowledge_documents")}

    if settings.database_url.startswith("sqlite"):
        required = {
            "object_key": "TEXT",
            "file_url": "TEXT",
            "file_size": "INTEGER NOT NULL DEFAULT 0",
            "storage_provider": "VARCHAR(32) NOT NULL DEFAULT 'minio'",
        }
    else:
        required = {
            "object_key": "VARCHAR(1024) NULL",
            "file_url": "VARCHAR(2048) NULL",
            "file_size": "BIGINT NOT NULL DEFAULT 0",
            "storage_provider": "VARCHAR(32) NOT NULL DEFAULT 'minio'",
        }

    with engine.begin() as conn:
        for column_name, definition in required.items():
            if column_name in existing_columns:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE knowledge_documents ADD COLUMN {column_name} {definition}"
            )


def _seed_admin_user(db: Session) -> None:
    from app.core.security import get_password_hash
    from app.models.user import User

    existing_usernames = {
        name for (name,) in db.query(User.username).filter(User.username.in_(["admin", "demo"])).all()
    }

    created = False
    if "admin" not in existing_usernames:
        admin_user = User(
            username="admin",
            password=get_password_hash("admin123"),
            nickname="系统管理员",
            role="admin",
            is_active=True,
        )
        db.add(admin_user)
        created = True

    if "demo" not in existing_usernames:
        demo_user = User(
            username="demo",
            password=get_password_hash("demo123"),
            nickname="演示用户",
            role="user",
            is_active=True,
        )
        db.add(demo_user)
        created = True

    if created:
        db.commit()


def _ensure_carbon_market_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    table = "carbon_market"
    with engine.begin() as conn:
        table_info = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        if not table_info:
            return
        existing_columns = {row[1] for row in table_info}
        required = {
            "allocation_method": "VARCHAR(64) NOT NULL DEFAULT 'benchmark'",
            "ccer_max_ratio": "REAL NOT NULL DEFAULT 0.30",
            "green_power_max_ratio": "REAL NOT NULL DEFAULT 0.20",
            "notes": "TEXT",
            "is_final": "BOOLEAN NOT NULL DEFAULT 0",
            "final_reason": "TEXT",
            "created_by": "INTEGER",
            "updated_at": "DATETIME",
            "updated_by": "INTEGER",
        }
        for column_name, definition in required.items():
            if column_name not in existing_columns:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}"
                )


def _ensure_cbam_data_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    table = "cbam_data"
    with engine.begin() as conn:
        table_info = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        if not table_info:
            return
        existing_columns = {row[1] for row in table_info}
        required = {
            "batch_id": "INTEGER",
            "product_category": "VARCHAR(128)",
            "footprint_scope": "VARCHAR(64)",
            "eu_price_date": "DATETIME",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'draft'",
            "notes": "TEXT",
            "created_by": "INTEGER",
            "updated_at": "DATETIME",
        }
        for column_name, definition in required.items():
            if column_name not in existing_columns:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}"
                )


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_public_institution_columns()
    _ensure_chat_history_columns()
    _ensure_chat_session_columns()
    _ensure_knowledge_document_columns()
    _ensure_carbon_market_columns()
    _ensure_cbam_data_columns()
    with SessionLocal() as db:
        _seed_factor_library(db)
        _seed_quick_questions(db)
        _seed_admin_user(db)
    _ensure_public_institution_columns()
