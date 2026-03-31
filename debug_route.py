"""Quick route-level debug for /api/finds/public"""
import asyncio
import sys
sys.path.insert(0, r'C:\Users\Pc\Desktop\FLUTTER\forago_backend')

from database import init_db
from queries import query_public_finds

async def main():
    await init_db()
    try:
        results = await query_public_finds()
        print(f"DB returned {len(results)} rows")
        for r in results:
            print("ROW:", r)
    except Exception as e:
        import traceback
        print("QUERY ERROR:")
        traceback.print_exc()

asyncio.run(main())
