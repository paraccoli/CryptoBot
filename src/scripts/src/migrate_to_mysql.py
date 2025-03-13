import sqlite3
import mysql.connector
from datetime import datetime
import os
from tqdm import tqdm
from dotenv import load_dotenv

def migrate_to_mysql():
    load_dotenv()  # .envファイルを読み込む
    
    # SQLite DBに接続
    sqlite_conn = sqlite3.connect('paraccoli.db')
    sqlite_cur = sqlite_conn.cursor()

    # MySQL DBに接続
    mysql_conn = mysql.connector.connect(
        host=os.getenv('MYSQL_HOST', 'localhost'),
        user=os.getenv('MYSQL_USER', 'root'),
        password=os.getenv('MYSQL_PASSWORD', 'yAsudamanuel1797463n7x00rknnsxB'),
        database=os.getenv('MYSQL_DATABASE', 'paraccoli')
    )
    mysql_cur = mysql_conn.cursor()

    try:
        # テーブル一覧を取得
        sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = sqlite_cur.fetchall()

        for table in tables:
            table_name = table[0]
            print(f"Migrating {table_name}...")

            # データを取得
            sqlite_cur.execute(f"SELECT * FROM {table_name}")
            rows = sqlite_cur.fetchall()

            if rows:
                # カラム情報を取得
                columns = [description[0] for description in sqlite_cur.description]
                placeholders = ', '.join(['%s'] * len(columns))
                columns_str = ', '.join(columns)

                # 一括挿入
                insert_query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
                
                for row in tqdm(rows):
                    mysql_cur.execute(insert_query, row)

                mysql_conn.commit()

    except Exception as e:
        print(f"Error during migration: {e}")
        mysql_conn.rollback()
    finally:
        sqlite_conn.close()
        mysql_conn.close()

if __name__ == "__main__":
    migrate_to_mysql()