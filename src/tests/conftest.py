import pytest
import sys
import os

# プロジェクトルートへのパスを追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

@pytest.fixture(scope="session")
def event_loop():
    """pytest-asyncioのためのイベントループ"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()