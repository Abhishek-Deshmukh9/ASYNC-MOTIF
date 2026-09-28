import asyncio
import os
import sys
import dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv.load_dotenv()
from app.core.pipeline import run_ai_pipeline

async def test():
    result = await run_ai_pipeline()
    print("SUCCESS: Pipeline finished with status:", result.get("status"))
    print("Themes generated count:", len(result.get("themes", [])))
    for t in result.get("themes", [])[:5]:
        print(f"- Theme: {t['title']} | Risk: ${t['revenue_at_risk']:,.0f} | Quotes: {len(t['cited_quotes'])}")

if __name__ == "__main__":
    asyncio.run(test())
