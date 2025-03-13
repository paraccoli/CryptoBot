from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import base64
import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy import func
from ..database.database import SessionLocal
from ..database.models import PriceHistory, Transaction
from ..utils.chart_builder import ChartBuilder
import matplotlib.pyplot as plt

# データマネージャークラス - WebSocketデータの更新・管理
class DataManager:
    def __init__(self):
        self.latest_data = {}
        self.last_update = datetime.now()
        self.logger = logging.getLogger("market_socket")
    
    def update_data(self, data):
        """新しいマーケットデータで更新"""
        self.latest_data = data
        self.last_update = datetime.now()
        
        # WebSocket接続に通知
        asyncio.create_task(notify_price_update(data))
    
    def update_random_prices(self, data):
        """ランダム価格情報を更新"""
        if "random_prices" not in self.latest_data:
            self.latest_data["random_prices"] = {}
        
        self.latest_data["random_prices"] = data
        
        # WebSocket接続に通知
        asyncio.create_task(notify_price_update({
            "type": "random_prices",
            "data": data
        }))
        
    def get_latest_data(self):
        """最新のマーケットデータを取得"""
        return self.latest_data

# クラスのインスタンスを作成
data_manager = DataManager()

# FastAPIアプリの作成
app = FastAPI(title="Paraccoli Market API")

# FastAPIアプリケーションにCORSミドルウェアを追加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://paraccoli.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ロガー設定
logger = logging.getLogger("market_api")

# アクティブなWebSocket接続を保持
active_connections: List[WebSocket] = []

# 最新のマーケットデータ
latest_market_data: Dict[str, Any] = {}

@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {"message": "Paraccoli Market API"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket接続エンドポイント"""
    await websocket.accept()
    active_connections.append(websocket)
    
    logger.info(f"Client connected. Total connections: {len(active_connections)}")
    
    try:
        # 接続時に最新データを送信
        if latest_market_data:
            await websocket.send_json(latest_market_data)
        
        # クライアントからのメッセージを待機
        while True:
            data = await websocket.receive_text()
            # クライアントからのメッセージは現時点では処理しない
            pass
            
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # 接続を閉じる際に接続リストから削除
        if websocket in active_connections:
            active_connections.remove(websocket)
            logger.info(f"Client removed. Remaining connections: {len(active_connections)}")

# WebSocket接続を通じて価格更新を通知する関数を更新
async def notify_price_update(data: Dict[str, Any]):
    """WebSocket接続を通じて価格更新を通知"""
    global latest_market_data
    
    # 通知データを作成
    message = {
        "type": "price_update",
        "data": data,
        "timestamp": datetime.now().timestamp()
    }
    
    # 最新データを更新
    latest_market_data = message
    
    # すべてのアクティブな接続に通知
    if not active_connections:
        return
        
    # 切断されたクライアントを追跡
    disconnected = []
    
    for conn in active_connections:
        try:
            await conn.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send update: {e}")
            disconnected.append(conn)
    
    # 切断されたクライアントを削除
    for conn in disconnected:
        active_connections.remove(conn)

@app.get("/api/crypto/market")
async def get_market_data():
    """マーケットデータを取得するAPIエンドポイント"""
    db = SessionLocal()
    try:
        # 最新の価格データを取得
        latest_price = db.query(PriceHistory)\
            .order_by(PriceHistory.timestamp.desc())\
            .first()
        
        if not latest_price:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "価格データが存在しません"}
            )
        
        # 24時間前の価格を取得して変動率を計算
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_price = db.query(PriceHistory)\
            .filter(PriceHistory.timestamp >= yesterday)\
            .order_by(PriceHistory.timestamp.asc())\
            .first()
            
        # 24時間取引量を取得
        volume_24h = db.query(func.sum(Transaction.amount))\
            .filter(
                Transaction.timestamp >= yesterday,
                Transaction.transaction_type.in_(['buy', 'sell'])
            ).scalar() or 0
            
        # 変動率の計算
        change_rate = 0.0
        if yesterday_price and latest_price:
            change_rate = ((latest_price.price - yesterday_price.price) 
                         / yesterday_price.price * 100)
            
        # チャート生成
        chart_path = os.path.join("temp", "website_chart.png")
        os.makedirs(os.path.dirname(chart_path), exist_ok=True)
        
        # 1時間分の価格履歴を取得
        hour_ago = datetime.now() - timedelta(hours=1)
        price_history = db.query(PriceHistory)\
            .filter(PriceHistory.timestamp >= hour_ago)\
            .order_by(PriceHistory.timestamp.asc())\
            .all()
            
        # チャート生成
        ChartBuilder.create_price_chart(price_history, chart_path, minutes=60)
            
        # 時価総額の計算
        total_supply = 100_000_000
        market_cap = float(latest_price.price) * total_supply
            
        # チャート画像をBase64エンコード
        chart_base64 = ""
        if os.path.exists(chart_path):
            with open(chart_path, "rb") as f:
                chart_base64 = base64.b64encode(f.read()).decode('utf-8')
                
        # レスポンスデータ
        return {
            "success": True,
            "data": {
                "price": {
                    "current": float(latest_price.price),
                    "change_rate": float(change_rate)
                },
                "volume": {
                    "24h": float(volume_24h)
                },
                "market_cap": float(market_cap),
                "timestamp": int(datetime.now().timestamp()),
                "chart": chart_base64
            }
        }
            
    except Exception as e:
        logger.error(f"Market data API error: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )
    finally:
        db.close()

@app.get("/api/crypto/market/latest")
async def get_latest_market_data():
    """最新のマーケットデータを取得するAPIエンドポイント"""
    if hasattr(data_manager, 'get_latest_data'):
        latest_data = data_manager.get_latest_data()
        if latest_data:
            return {
                "success": True,
                "data": latest_data
            }
    
    # データがない場合は従来のエンドポイントにリダイレクト
    return await get_market_data()

# WebSocketサーバーを開始する関数
async def start_server(host="0.0.0.0", port=8000):
    """FastAPI WebSocketサーバーを開始"""
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Starting WebSocket server on {host}:{port}")
    
    # サーバーをバックグラウンドで実行
    await server.serve()
    return server