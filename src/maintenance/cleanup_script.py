#!/usr/bin/env python3
# filepath: /home/paraccoli/project_paraccoli/ProjectParaccoli/ParaccoliCrypto/src/maintenance/cleanup_script.py
import os
import shutil
import time
import logging
from datetime import datetime, timedelta
import sys

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/maintenance.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("maintenance")

def cleanup_logs():
    """logsフォルダ内のファイルをすべて削除する"""
    try:
        log_dir = "logs"
        logger.info("logsフォルダの全ファイルを削除します...")
        
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logger.info(f"ログディレクトリを作成: {log_dir}")
            return
            
        # 削除前にバックアップを作成（最新のログは残しておく）
        current_log_file = f"paraccoli_{datetime.now().strftime('%Y%m%d')}.log"
        current_log_path = os.path.join(log_dir, current_log_file)
        maintenance_log = os.path.join(log_dir, "maintenance.log")
        
        # バックアップディレクトリ作成
        backup_dir = os.path.join("backup", "logs_backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        # 現在のログとメンテナンスログをバックアップ
        if os.path.exists(current_log_path):
            backup_path = os.path.join(backup_dir, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{current_log_file}")
            shutil.copy2(current_log_path, backup_path)
            logger.info(f"現在のログをバックアップしました: {backup_path}")
            
        if os.path.exists(maintenance_log):
            backup_path = os.path.join(backup_dir, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_maintenance.log")
            shutil.copy2(maintenance_log, backup_path)
            logger.info(f"メンテナンスログをバックアップしました: {backup_path}")
        
        # ログファイルを全て削除（メンテナンスログは除く）
        deleted_count = 0
        for file in os.listdir(log_dir):
            file_path = os.path.join(log_dir, file)
            if os.path.isfile(file_path) and file != "maintenance.log":
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"ログファイル削除エラー: {file} - {e}")
        
        logger.info(f"logsフォルダ内のファイルを削除しました: {deleted_count}ファイル")
        
    except Exception as e:
        logger.error(f"ログクリーンアップエラー: {e}", exc_info=True)

def cleanup_temp_folder():
    """tempフォルダ内の古いファイルを削除"""
    try:
        temp_dir = "temp"
        
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            logger.info(f"tempディレクトリを作成: {temp_dir}")
            return
            
        # 30分以上前のファイルを削除（チャートは頻繁に作成されるため）
        cutoff_time = time.time() - (30 * 60)  # 30分前
        
        deleted_count = 0
        for item in os.listdir(temp_dir):
            item_path = os.path.join(temp_dir, item)
            try:
                if os.path.isfile(item_path):
                    if os.path.getmtime(item_path) < cutoff_time:
                        os.remove(item_path)
                        deleted_count += 1
                elif os.path.isdir(item_path):
                    if os.path.getmtime(item_path) < cutoff_time:
                        shutil.rmtree(item_path)
                        deleted_count += 1
            except Exception as e:
                logger.error(f"temp削除エラー: {item} - {e}")
        
        logger.info(f"tempフォルダ内の古いファイル削除完了: {deleted_count}アイテム削除")
        
    except Exception as e:
        logger.error(f"tempフォルダクリーンアップエラー: {e}")

def cleanup_backup_charts():
    """バックアップフォルダ内のchartsデータを削除"""
    try:
        backup_dir = "backup"
        
        if not os.path.exists(backup_dir):
            logger.warning(f"バックアップフォルダが存在しません: {backup_dir}")
            return
            
        # 3時間以上前のバックアップのchartsフォルダを削除
        cutoff_time = time.time() - (3 * 60 * 60)  # 3時間
        
        deleted_count = 0
        for date_folder in os.listdir(backup_dir):
            date_folder_path = os.path.join(backup_dir, date_folder)
            
            # データフォルダのみ処理（日付形式のフォルダ）
            if not os.path.isdir(date_folder_path) or not date_folder[0].isdigit():
                continue
                
            charts_folder = os.path.join(date_folder_path, 'charts')
            if os.path.exists(charts_folder) and os.path.isdir(charts_folder):
                # chartsフォルダの更新時間をチェック
                try:
                    if os.path.getmtime(charts_folder) < cutoff_time:
                        shutil.rmtree(charts_folder)
                        logger.info(f"古いchartsフォルダを削除: {charts_folder}")
                        deleted_count += 1
                except Exception as e:
                    logger.error(f"chartsフォルダ削除エラー: {charts_folder} - {e}")
        
        logger.info(f"バックアップ内のチャートデータクリーンアップ完了: {deleted_count}フォルダ削除")
        
    except Exception as e:
        logger.error(f"バックアップchartsフォルダクリーンアップエラー: {e}")

if __name__ == "__main__":
    # スクリプトが実行されたディレクトリをプロジェクトのルートディレクトリに変更
    project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.chdir(project_path)
    
    logger.info(f"=== メンテナンススクリプト実行開始（パス: {project_path}） ===")
    
    # logsフォルダのクリーンアップ
    cleanup_logs()
    
    # tempフォルダのクリーンアップ
    cleanup_temp_folder()
    
    # バックアップchartsフォルダのクリーンアップ
    cleanup_backup_charts()
    
    logger.info("=== メンテナンススクリプト実行完了 ===")