#!/usr/bin/env python3
"""
Test if LLM preserves link tokens
"""
import sys
import asyncio
sys.path.insert(0, '/Users/aggel008/attention_log_bot')

from services.llm import LLMService
from config import load_config

async def test_llm():
    config = load_config()
    llm = LLMService(config)

    # Test text with tokens
    test_text = """Проверка токенов ⟦LINK:0⟧ и ещё один токен ⟦LINK:1⟧ в тексте."""

    print("=" * 60)
    print("TESTING LLM TOKEN PRESERVATION")
    print("=" * 60)
    print("\nInput text:")
    print(test_text)

    instruction = (
        "Перепиши текст, сохранив все токены вида ⟦LINK:N⟧ в точности как есть. "
        "КРИТИЧЕСКИ ВАЖНО: каждый токен ОБЯЗАН остаться в выходном тексте."
    )

    try:
        result = await llm._make_request(instruction, test_text)

        print("\nLLM response:")
        print(result)

        # Check if tokens are preserved
        print("\n" + "=" * 60)
        print("TOKEN VERIFICATION")
        print("=" * 60)

        tokens = ["⟦LINK:0⟧", "⟦LINK:1⟧"]
        for token in tokens:
            if token in result:
                print(f"✓ {token} PRESERVED")
            else:
                print(f"✗ {token} LOST")

                # Check for similar patterns
                if "[LINK:0]" in result or "[LINK:1]" in result:
                    print(f"  ! Found with square brackets instead of ⟦⟧")
                if "LINK:0" in result or "LINK:1" in result:
                    print(f"  ! Found without brackets")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_llm())
