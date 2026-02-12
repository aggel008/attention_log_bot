#!/usr/bin/env python3
"""
Test script to verify link extraction and restoration logic
"""
import sys
sys.path.insert(0, '/Users/aggel008/attention_log_bot')

from services.llm import LLMService
from config import load_config

# Mock entities for testing
test_entities = [
    {"type": "text_link", "offset": 10, "length": 11, "url": "https://example.com/1"},
    {"type": "text_link", "offset": 50, "length": 5, "url": "https://example.com/2"},
    {"type": "url", "offset": 80, "length": 23, "url": None},  # url type has no url field
]

test_text = """Проверка встроенной ссылки здесь и еще одна ссылка
тут, а также обычный URL https://example.com/3 в тексте."""

# Manually set offsets correctly for test
test_entities = [
    {"type": "text_link", "offset": 27, "length": 5, "url": "https://example.com/1"},  # "здесь"
    {"type": "text_link", "offset": 51, "length": 3, "url": "https://example.com/2"},  # "тут"
    {"type": "url", "offset": 76, "length": 21, "url": None},  # "https://example.com/3"
]

print("=" * 60)
print("TESTING LINK EXTRACTION")
print("=" * 60)

config = load_config()
llm = LLMService(config)

print("\nOriginal text:")
print(test_text)
print(f"\nEntities: {len(test_entities)}")
for e in test_entities:
    print(f"  - {e}")

# Test extraction
text_with_tokens, links = llm._extract_all_links(test_text, test_entities)

print("\n" + "=" * 60)
print("AFTER EXTRACTION")
print("=" * 60)
print("\nText with tokens:")
print(text_with_tokens)
print(f"\nExtracted links: {len(links)}")
for token, data in links.items():
    print(f"  {token} -> anchor={data['anchor']}, url={data['url']}")

# Simulate LLM processing (just return the same text)
llm_response = text_with_tokens

print("\n" + "=" * 60)
print("TESTING RESTORATION")
print("=" * 60)
print("\nLLM response (simulated - same as input):")
print(llm_response)

# Test restoration
restored_text, restored_entities = llm._restore_all_links(llm_response, links)

print("\nRestored text:")
print(restored_text)
print(f"\nRestored entities: {len(restored_entities)}")
for e in restored_entities:
    print(f"  - {e}")

print("\n" + "=" * 60)
print("VERIFICATION")
print("=" * 60)
print(f"Original entities count: {len(test_entities)}")
print(f"Restored entities count: {len(restored_entities)}")
print(f"Match: {len(test_entities) == len(restored_entities)}")
