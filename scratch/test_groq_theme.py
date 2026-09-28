import os
import asyncio
import dotenv
import httpx

dotenv.load_dotenv()
key = os.getenv("GROQ_API_KEY")

async def test():
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    prompt = """Synthesize the following representative customer feedback items into a structured theme:
[1] Customer 'enterprise_101' (enterprise, ARR: $120,000):
"Whenever our team attempts to export audit logs spanning more than 90 days, the UI hangs indefinitely and eventually terminates with a 504 Gateway Timeout error. This halts our SOC2 compliance audit."
[2] Customer 'enterprise_104' (enterprise, ARR: $95,000):
"Audit log export fails consistently for datasets exceeding 50,000 rows. We see 504 Gateway Timeout and no data is downloaded."

Provide strictly the JSON object. Do not include markdown code block backticks."""

    sys_prompt = """You are Motif's Autonomous Feedback-to-Backlog Synthesis Engine.
Your task is to analyze a cluster of related customer feedback items and synthesize a structured product backlog theme.

NON-NEGOTIABLE CORE AXIOM:
Every claim in your output must be directly grounded in the provided customer feedback items.
In particular, `cited_quotes` MUST be a list of EXACT VERBATIM SUBSTRINGS copied directly from the feedback items below.
Never paraphrase, alter, or fabricate any quote. Every single quote will be verified by a deterministic string-matching engine.

You MUST respond strictly with valid JSON conforming to this schema:
{
  "title": "<Concise theme title>",
  "problem_statement": "<Objective technical summary>",
  "affected_workflows": ["<Workflow 1>"],
  "cited_quotes": ["<exact verbatim quote 1>"],
  "confidence_score": 0.95
}"""

    for model in ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]:
        print(f"Testing model: {model}")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            print("Status:", r.status_code)
            print("Response:", r.text)

if __name__ == "__main__":
    asyncio.run(test())
