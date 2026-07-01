import asyncio
from app.database import engine
import sqlalchemy as sa

async def check():
    async with engine.begin() as conn:
        q = sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = 'check_logs' ORDER BY ordinal_position")
        result = await conn.execute(q)
        cols = [r[0] for r in result.fetchall()]
        print("check_logs columns:", cols)

asyncio.run(check())
