"""
Full schema migration — fixes all legacy DB issues.
Run once; safe to run multiple times.
"""
import asyncio
import sqlalchemy as sa
from app.database import engine


async def main():
    async with engine.begin() as conn:

        # --- host_services: add columns new model expects ---
        r = await conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='host_services'"
        ))
        hs_cols = {x[0] for x in r.fetchall()}
        print("host_services existing:", sorted(hs_cols))

        for col, defn in [
            ("response_time_ms",   "INTEGER"),
            ("last_checked_at",    "TIMESTAMP"),
            ("ssl_days_remaining", "INTEGER"),
            ("last_error",         "TEXT"),
        ]:
            if col not in hs_cols:
                await conn.execute(sa.text(
                    f"ALTER TABLE host_services ADD COLUMN IF NOT EXISTS {col} {defn}"
                ))
                print(f"  Added host_services.{col}")
            else:
                print(f"  host_services.{col} OK")

        # --- check_logs: make resource_id nullable ---
        await conn.execute(sa.text(
            "ALTER TABLE check_logs ALTER COLUMN resource_id DROP NOT NULL"
        ))
        print("check_logs.resource_id is now nullable")

        # --- check_logs: add new columns ---
        r2 = await conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='check_logs'"
        ))
        cl_cols = {x[0] for x in r2.fetchall()}
        for col, defn in [
            ("service_id",         "INTEGER"),
            ("ssl_days_remaining", "INTEGER"),
            ("error_message",      "TEXT"),
        ]:
            if col not in cl_cols:
                await conn.execute(sa.text(
                    f"ALTER TABLE check_logs ADD COLUMN IF NOT EXISTS {col} {defn}"
                ))
                print(f"  Added check_logs.{col}")
            else:
                print(f"  check_logs.{col} OK")

        # --- users: add new columns ---
        r3 = await conn.execute(sa.text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
        ))
        u_cols = {x[0] for x in r3.fetchall()}
        for col, defn in [
            ("first_name", "VARCHAR(100)"),
            ("last_name",  "VARCHAR(100)"),
            ("phone",      "VARCHAR(30)"),
            ("is_active",  "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("deleted_at", "TIMESTAMP"),
        ]:
            if col not in u_cols:
                await conn.execute(sa.text(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}"
                ))
                print(f"  Added users.{col}")
            else:
                print(f"  users.{col} OK")

    print("\nAll schema fixes complete. Restart the server.")


if __name__ == "__main__":
    asyncio.run(main())
