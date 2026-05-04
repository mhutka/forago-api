import asyncio
from queries import query_public_finds

async def main():
    try:
        results = await query_public_finds()
        print("OK, records:", len(results))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e))

if __name__ == "__main__":
    asyncio.run(main())
