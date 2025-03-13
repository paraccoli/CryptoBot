import pytest
from datetime import datetime, timedelta
import sys
import os

# プロジェクトルートへのパスを追加
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.utils.price_predictor import PricePredictor
from src.database.models import PriceHistory
from src.database.database import SessionLocal

class TestPricePredictor:
    @pytest.fixture
    def predictor(self):
        return PricePredictor()

    @pytest.fixture
    async def mock_price_data(self):
        now = datetime.utcnow()
        return [
            PriceHistory(
                timestamp=now - timedelta(hours=i),
                price=100 + i,
                volume=1000
            )
            for i in range(24)
        ]

    @pytest.mark.asyncio
    async def test_predict_price_success(self, predictor, mock_price_data, mocker):
        # DBモック
        mock_session = mocker.Mock()
        mock_session.query.return_value.filter.return_value.\
            order_by.return_value.all.return_value = mock_price_data
        mocker.patch('src.database.database.SessionLocal', return_value=mock_session)

        result = await predictor.predict_price(hours=1)
        assert result['success'] is True
        assert 'predicted_price' in result
        assert 'confidence' in result
        assert 'graph' in result

    async def test_predict_price_insufficient_data(self, predictor, mocker):
        # 不十分なデータでのテスト
        mock_session = mocker.Mock()
        mock_session.query.return_value.filter.return_value.\
            order_by.return_value.all.return_value = []
        mocker.patch('src.database.database.SessionLocal', return_value=mock_session)

        result = await predictor.predict_price(hours=1)
        assert result['success'] == False
        assert "十分なデータがありません" in result['error']