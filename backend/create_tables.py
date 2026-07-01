"""
Create any missing tables by running create_all with all models loaded.
"""
import asyncio
from app.database import engine, Base

# Import ALL models so metadata is populated
import app.models  # noqa: F401


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("All tables created/verified.")

    # Also verify they exist
    import sqlalchemy as sa
    async with engine.begin() as conn:
        for tbl in ["users", "hosts", "host_services", "check_logs", "event_logs", "app_settings"]:
            r = await conn.execute(sa.text(
                f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name='{tbl}'"
            ))
            exists = r.scalar() > 0
            print(f"  {tbl}: {'EXISTS' if exists else 'MISSING!'}")


if __name__ == "__main__":
    asyncio.run(main())
