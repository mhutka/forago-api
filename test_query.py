import asyncio
import sys
sys.path.insert(0, r'C:\Users\Pc\Desktop\FLUTTER\forago_backend')
from queries import query_public_finds

async def main():
    try:
        results = await query_public_finds()
        print("OK, records:", len(results))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e))

asyncio.run(main())
