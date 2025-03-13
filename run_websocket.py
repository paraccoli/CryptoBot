import uvicorn
from src.websocket.market_socket import app
import asyncio
import logging
import os
from datetime import datetime

# ログ設定
def setup_websocket_logger():
    """WebSocketサーバーのログ設定"""
    logger = logging.getLogger('websocket_server')
    logger.setLevel(logging.INFO)
    
    # ログディレクトリ作成
    os.makedirs('logs', exist_ok=True)
    log_file = f'logs/websocket_{datetime.now().strftime("%Y%m%d")}.log'
    
    # ファイルハンドラ
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    
    # コンソールハンドラ
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter('%(message)s')
    )
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

async def start_server():
    """WebSocketサーバーを開始"""
    logger = setup_websocket_logger()
    
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=8001, 
        loop="asyncio",
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    try:
        logger.info("WebSocketサーバーを開始します")
        await server.serve()
    except Exception as e:
        logger.error(f"サーバー起動エラー: {e}")

if __name__ == "__main__":
    asyncio.run(start_server())