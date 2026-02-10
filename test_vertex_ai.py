#!/usr/bin/env python3
"""
Test script to validate Vertex AI connection and GPTService functionality.
"""
import asyncio
import logging
import sys
from config import load_config
from services.gpt import GPTService

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
_log = logging.getLogger(__name__)

async def test_vertex_ai():
    """Test Vertex AI connection with a simple rewrite request."""
    try:
        _log.info("Loading configuration...")
        config = load_config()

        _log.info("Initializing GPTService with Vertex AI...")
        gpt_service = GPTService(config)

        _log.info(f"Testing rewrite_text() with model: {config.vertex_model}")
        test_text = "Сегодня я узнал интересную вещь про нейросети. Они могут помочь переписывать тексты."

        result_text, result_entities = await gpt_service.rewrite_text(test_text)

        _log.info("=" * 60)
        _log.info("✅ SUCCESS! Vertex AI is working correctly.")
        _log.info("=" * 60)
        _log.info(f"Model used: {config.vertex_model}")
        _log.info(f"Project: {config.vertex_project_id}")
        _log.info(f"Location: {config.vertex_location}")
        _log.info("-" * 60)
        _log.info(f"Original text:\n{test_text}")
        _log.info("-" * 60)
        _log.info(f"Rewritten text:\n{result_text}")
        _log.info("-" * 60)
        _log.info(f"Entities: {result_entities}")
        _log.info("=" * 60)

        return True

    except Exception as e:
        _log.error(f"❌ FAILED! Error during Vertex AI test: {e}", exc_info=True)
        return False

if __name__ == '__main__':
    success = asyncio.run(test_vertex_ai())
    sys.exit(0 if success else 1)
