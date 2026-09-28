import asyncio
import os
import dotenv
import httpx

dotenv.load_dotenv()
key = os.getenv("GROQ_API_KEY")

async def test_model(model_name: str):
    print(f"\nTesting model: {model_name}")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You respond strictly in valid JSON format."},
            {"role": "user", "content": 'Respond with {"status": "ok", "model": "' + model_name + '"}'},
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            print("Status code:", r.status_code)
            if r.status_code == 200:
                print("Content:", r.json()["choices"][0]["message"]["content"])
                return True
            else:
                print("Error:", r.text[:200])
                return False
        except Exception as e:
            print("Exception:", e)
            return False

async def main():
    for m in ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"]:
        success = await test_model(m)
        if success:
            print(f"--> {m} works perfectly on Groq!")

if __name__ == "__main__":
    asyncio.run(main())
