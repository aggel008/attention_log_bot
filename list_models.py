#!/usr/bin/env python3
"""
Script to list available models in Vertex AI
"""
import asyncio
from google import genai

async def list_models():
    client = genai.Client(
        vertexai=True,
        project="gen-lang-client-0116875412",
        location="us-central1"
    )

    print("Listing available models...")
    try:
        models = await client.aio.models.list()
        print("\nAvailable models:")
        async for model in models:
            print(f"  - {model.name}")
            if hasattr(model, 'display_name'):
                print(f"    Display: {model.display_name}")
    except Exception as e:
        print(f"Error listing models: {e}")
        print("\nTrying to list Claude models specifically...")

        # Try specific Claude model names
        claude_models = [
            "claude-3-5-sonnet@20240620",
            "claude-3-5-sonnet-v2@20241022",
            "claude-3-opus@20240229",
            "claude-3-sonnet@20240229",
            "claude-3-haiku@20240307",
        ]

        for model_name in claude_models:
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents="test"
                )
                print(f"✅ {model_name} - WORKS")
            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg:
                    print(f"❌ {model_name} - NOT FOUND")
                elif "403" in error_msg:
                    print(f"⚠️  {model_name} - NO ACCESS (billing?)")
                else:
                    print(f"❌ {model_name} - ERROR: {error_msg[:100]}")

if __name__ == '__main__':
    asyncio.run(list_models())
