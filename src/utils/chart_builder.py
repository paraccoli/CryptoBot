# src/utils/chart_builder.py
from matplotlib import pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.figure import Figure
import numpy as np
from ..database.models import PriceHistory
import seaborn as sns
import pandas as pd
from datetime import datetime, timedelta, timezone
import pytz
import os
import random
import matplotlib.font_manager as fm
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from discord import Embed, Colour
from ..utils.trading_hours import TradingHours
import platform

def setup_fonts():
    """日本語および絵文字対応フォントを設定"""
    try:
        font_path = None
        if os.name == 'nt':  # Windows
            font_path = "C:\\Windows\\Fonts\\msgothic.ttc"  # MS Gothic
        else:
            font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"  # Linux (Noto Sans CJK)

        if font_path and os.path.exists(font_path):
            prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = prop.get_name()
        else:
            plt.rcParams['font.family'] = 'Arial Unicode MS'  # 絵文字対応フォント

        plt.rcParams['axes.unicode_minus'] = False  # マイナス記号の文字化け防止
    except Exception as e:
        print(f"フォント設定エラー: {e}")
    
def configure_matplotlib_fonts():
    """
    Matplotlibのフォント設定を行う関数
    実行環境に応じた最適なフォントを選択する
    """
    # デバッグ情報表示
    print(f"フォント設定を開始します: プラットフォーム={platform.system()}")
    
    # フォールバック用のフォントリスト（優先順に）
    font_candidates = [
        # Linux一般的な日本語フォント
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/opentype/ipaexfont/ipaexg.ttf',
        # Ubuntuの一般的なフォント
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        # CentOS/RHEL系
        '/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc',
        # macOS
        '/System/Library/Fonts/ヒラギノ角ゴシック.ttc',
        # Windows
        'C:/Windows/Fonts/msgothic.ttc',
    ]
    
    # 使用可能なフォントを探す
    font_path = None
    for candidate in font_candidates:
        if os.path.exists(candidate):
            font_path = candidate
            print(f"フォントが見つかりました: {font_path}")
            break
    
    # フォントパスが見つからない場合のフォールバック
    if font_path is None:
        # matplotlibのシステムフォントを探す
        system_fonts = fm.findSystemFonts()
        
        # 日本語対応の可能性があるフォントを優先して探す
        jp_keywords = ['noto', 'gothic', 'sans', 'mincho', 'jp', 'cjk']
        
        for font in system_fonts:
            font_lower = font.lower()
            if any(keyword in font_lower for keyword in jp_keywords):
                font_path = font
                print(f"日本語対応の可能性があるフォントを見つけました: {font_path}")
                break
        
        # それでも見つからない場合はデフォルト設定
        if font_path is None:
            print("適切なフォントが見つかりませんでした。デフォルト設定を使用します。")
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Bitstream Vera Sans', 'Arial', 'sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            return
    
    # フォントの登録と設定
    try:
        font_prop = fm.FontProperties(fname=font_path)
        fm.fontManager.addfont(font_path)
        
        # フォント名を識別して適切に設定
        font_name = font_prop.get_name()
        print(f"フォント名: {font_name}")
        
        if "noto" in font_path.lower():
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'Noto Sans', 'DejaVu Sans', 'sans-serif']
        elif "dejavu" in font_path.lower():
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'sans-serif']
        elif "msgothic" in font_path.lower() or "gothic" in font_path.lower():
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['MS Gothic', 'IPAGothic', 'sans-serif']
        elif "hiragino" in font_path.lower():
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['Hiragino Sans', 'sans-serif']
        elif "ipag" in font_path.lower() or "ipa" in font_path.lower():
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = ['IPAGothic', 'IPAexGothic', 'sans-serif']
        else:
            # 一般的なフォント設定
            plt.rcParams['font.family'] = 'sans-serif'
            plt.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans', 'sans-serif']
    except Exception as e:
        print(f"フォント設定エラー: {e}")
        # エラーの場合はデフォルト設定
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'sans-serif']
    
    # 日本語を正しく表示させるための設定
    plt.rcParams['axes.unicode_minus'] = False
    
    print(f"フォント設定完了: {plt.rcParams['font.family']}")
    if isinstance(plt.rcParams['font.sans-serif'], list):
        print(f"フォント候補リスト: {plt.rcParams['font.sans-serif']}")

class ChartBuilder:
    # 10秒ごとの価格履歴を保存する静的変数
    _realtime_history = []  # [(timestamp, price), ...]
    _max_history_length = 360  # 60分分（10秒×6×60）のデータを保持
    _latest_calculated_price = None  # 最新の計算済み価格
    _latest_calculated_time = None   # 最新の価格計算時刻
    
    @staticmethod
    def initialize():
        """静的変数を確実に初期化する"""
        if not hasattr(ChartBuilder, '_realtime_history') or ChartBuilder._realtime_history is None:
            ChartBuilder._realtime_history = []
            print("ChartBuilder._realtime_history を初期化しました")
        
        # 履歴の最大長を60分（10秒間隔で360点）に設定
        # 実際の表示は10分間のみだが、長めに履歴は保存しておく
        if not hasattr(ChartBuilder, '_max_history_length'):
            ChartBuilder._max_history_length = 360  # 10秒間隔で60分分
            
        if not hasattr(ChartBuilder, '_latest_calculated_price'):
            ChartBuilder._latest_calculated_price = None
            
        if not hasattr(ChartBuilder, '_latest_calculated_time'):
            ChartBuilder._latest_calculated_time = None
        
        # フォント設定を行う
        configure_matplotlib_fonts()
            
        print(f"ChartBuilder 初期化完了: 履歴データ数={len(ChartBuilder._realtime_history)}件")

    @staticmethod
    def set_calculated_price(price, timestamp=None):
        """価格計算で算出された実際の価格を設定"""
        if timestamp is None:
            timestamp = datetime.now()
            
        # タイムゾーン情報が無い場合は追加
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
            
        print(f"計算価格を設定: 時間={timestamp}, 価格=¥{price:,.2f}")
        # 計算価格を保存
        ChartBuilder._latest_calculated_price = price
        ChartBuilder._latest_calculated_time = timestamp
        
        # 計算価格も履歴に追加（計算価格は信頼性の高いポイントなので保存）
        ChartBuilder.update_realtime_history(price, timestamp)

    @staticmethod
    def update_realtime_history(price, timestamp=None):
        """10秒ごとの価格履歴を更新する"""
        if timestamp is None:
            timestamp = datetime.now()
        
        # タイムゾーン情報が無い場合は追加
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()  # ローカルタイムゾーンを使用
            
        print(f"リアルタイム履歴に追加: 時間={timestamp.strftime('%H:%M:%S')}, 価格=¥{price:,.2f}")
        ChartBuilder._realtime_history.append((timestamp, price))
        
        # 厳密に10分間のデータのみを保持
        current_time = datetime.now().astimezone()
        cutoff_time = current_time - timedelta(minutes=10)
        
        # 10分以上前のデータを削除
        old_count = len(ChartBuilder._realtime_history)
        ChartBuilder._realtime_history = [(t, p) for t, p in ChartBuilder._realtime_history if t >= cutoff_time]
        new_count = len(ChartBuilder._realtime_history)
        
        if old_count != new_count:
            print(f"古いデータを削除しました: {old_count - new_count}件 (残り: {new_count}件)")
        
        print(f"現在の履歴データ数: {new_count}件 (最新10分間のみ保持)")

    @staticmethod
    def generate_interpolated_price(current_time=None):
        """計算価格間を補間したランダム値を生成"""
        if current_time is None:
            current_time = datetime.now().astimezone()
            
        # 計算価格が設定されていない場合はNoneを返す
        if ChartBuilder._latest_calculated_price is None or ChartBuilder._latest_calculated_time is None:
            print("計算価格が未設定のため補間価格を生成できません")
            return None
        
        # 最新の履歴データを取得
        if not ChartBuilder._realtime_history:
            print("履歴データがないため最新の計算価格を返します")
            return ChartBuilder._latest_calculated_price
        
        last_time, last_price = ChartBuilder._realtime_history[-1]
        
        # 最新の計算価格からの経過時間（秒）
        elapsed_seconds = (current_time - ChartBuilder._latest_calculated_time).total_seconds()
        
        # 変動幅を±5%に制限する
        max_price_change = 0.05  # 最大±5%
        
        # 前回のデータからの変化率（±0.5%まで）
        variation_from_last = random.uniform(-0.005, 0.005)  # ±0.5%のランダム変動
        
        # 前回の価格に小さな変動を適用
        new_price = last_price * (1 + variation_from_last)
        
        # 価格計算値に向かって徐々に収束する傾向を加える
        if elapsed_seconds < 60:  # 1分以内は計算価格を基準に
            # 1分以内は計算価格を基準に、少しずつランダム変動
            max_variation = min(0.02, elapsed_seconds / 300)  # 最大2%まで、経過時間に応じて増加
            new_price = ChartBuilder._latest_calculated_price * (1 + random.uniform(-max_variation, max_variation))
        else:
            # 1分以上経過した場合は前回値からの変動を主体に
            # 計算値からの変動は最大±5%を超えないようにする
            base_variation = abs(new_price - ChartBuilder._latest_calculated_price) / ChartBuilder._latest_calculated_price
            if base_variation > max_price_change:
                # 変動が大きすぎる場合は計算値の方向に引き戻す
                direction = 1 if new_price > ChartBuilder._latest_calculated_price else -1
                max_allowed = ChartBuilder._latest_calculated_price * (1 + max_price_change * direction)
                new_price = max_allowed
        
        # 2桁に丸める
        new_price = round(new_price, 2)
        
        print(f"補間価格を生成: ¥{new_price:,.2f} (計算価格からの経過: {elapsed_seconds:.1f}秒, 変動率: {((new_price/ChartBuilder._latest_calculated_price)-1)*100:+.2f}%)")
        return new_price

    @staticmethod
    def create_price_chart(price_history, save_path: str, minutes: int = 60):
        """
        価格チャートの作成
        Args:
            price_history: 価格履歴データ
            save_path: 保存パス
            minutes: グラフの表示期間(分) - 10, 30, 60のいずれか
        """
        
        # 指定期間のデータのみ使用
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        filtered_history = [p for p in price_history if p.timestamp > cutoff_time]
        
        if not filtered_history:
            # データがない場合は空のチャートを生成
            plt.figure(figsize=(12, 8))
            plt.title(f'データがありません({minutes}分チャート)', color='white')
            plt.savefig(save_path, facecolor='#2f3136')
            plt.close()
            return
        
        # データの準備
        # ローカルタイムゾーンを使用
        local_tz = datetime.now().astimezone().tzinfo
        dates = [p.timestamp.replace(tzinfo=local_tz) if p.timestamp.tzinfo is None else p.timestamp for p in filtered_history]
        prices = [p.price for p in filtered_history]
        current_price = prices[-1] if prices else 0

        # 2段組のグラフを作成
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1])
        fig.patch.set_facecolor('#2f3136')

        # 価格チャートの描画（上段）
        ax1.set_facecolor('#2f3136')
        
        # 日付をmatplotlibの日付形式に変換
        dates_num = mdates.date2num(dates)
        
        # 現在価格より上下で色分けするためのセグメント作成
        points = np.array([dates_num, prices]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        
        # 色分けの条件作成
        colors = ['#ff4444' if p < current_price else '#44ff44' for p in prices[1:]]
        
        # LineCollectionを使用して色分けされた線を描画
        lc = LineCollection(segments, colors=colors, linewidth=2)
        ax1.add_collection(lc)
        
        # 現在価格の水平線を追加
        ax1.axhline(y=current_price, color='yellow', linestyle='--', alpha=0.3, linewidth=1)
        ax1.text(dates[-1], current_price, f'¥{current_price:,.2f}', 
                color='yellow', va='bottom', ha='right')
        
        # 各ポイントを点として表示
        ax1.scatter(dates, prices, color='white', s=20)
        
        # グラフの設定
        ax1.grid(True, color='gray', alpha=0.2)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['bottom'].set_color('white')
        ax1.spines['left'].set_color('white')
        ax1.tick_params(colors='white')
        
        # 横軸の設定を修正 - 表示期間に応じて適切な間隔を設定
        if minutes <= 10:  # 10分以内
            ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))  # 1分間隔
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        elif minutes <= 30:  # 30分以内
            ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))  # 5分間隔
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        else:  # 60分
            ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))  # 10分間隔
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        
        # 日付ラベルを見やすく回転
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        # 軸の範囲設定
        ax1.set_xlim(dates[0], dates[-1] + timedelta(minutes=1))  # 右側に少し余白
        
        # 価格範囲の計算を現在価格を中心に変更
        max_diff = max(abs(max(prices) - current_price), abs(min(prices) - current_price))
        padding = max_diff * 0.2  # 20%の余白
        
        y_min = max(0, current_price - max_diff - padding)  # 0以下にならないように調整
        y_max = current_price + max_diff + padding
        
        # グラフの表示範囲を設定（現在価格を中心に）
        ax1.set_ylim(y_min, y_max)

        # タイトルに表示期間を追加
        ax1.set_title(f'PARC/JPY チャート ({minutes}分間)', color='white', fontsize=14, pad=10)
        ax1.set_ylabel('価格 (JPY)', color='white', fontsize=12)



        # センチメントメーター(下段)
        ax2.set_facecolor('#2f3136')
        
        # 横軸バーの設定
        bar_height = 0.2
        y_position = 0.5
        
        # セクションの定義と描画
        sections = [
            {'range': (0.0, 0.33), 'color': '#ff4444', 'label': '買い優勢'},   # 赤
            {'range': (0.33, 0.67), 'color': '#ffff44', 'label': '中立相場'},  # 黄
            {'range': (0.67, 1.0), 'color': '#44ff44', 'label': '売り優勢'}    # 緑
        ]
        
        for section in sections:
            x_start = -1.0 + (section['range'][0] * 2)
            x_end = -1.0 + (section['range'][1] * 2)
            ax2.fill_between([x_start, x_end], 
                           y_position - bar_height/2,
                           y_position + bar_height/2,
                           color=section['color'],
                           alpha=0.3)

        # センチメント値の計算と表示
        if len(price_history) >= 2:
            # 始値と終値を使用して変動率を計算
            change_rate = ((price_history[-1].price - price_history[0].price) / price_history[0].price * 100)
            
            # センチメントの計算(変動率に基づく)
            sentiment = 0.5  # デフォルトは中立
            if change_rate > 1:
                sentiment = 0.8  # 売り優勢
            elif change_rate < -1:
                sentiment = 0.2  # 買い優勢
        else:
            sentiment = 0.5
            change_rate = 0.0

        # マーカー位置の計算と描画
        marker_x = -1.0 + (sentiment * 2)
        marker_height = bar_height * 1.5
        triangle = plt.Polygon([
            [marker_x, y_position + marker_height/2],
            [marker_x - 0.05, y_position - marker_height/2],
            [marker_x + 0.05, y_position - marker_height/2]
        ], color='white')
        ax2.add_patch(triangle)

        # ラベル表示
        ax2.text(-0.9, y_position + 0.4, '買い優勢', color='#ff4444', 
                fontsize=12, fontweight='bold', ha='left')
        ax2.text(0, y_position + 0.4, '中立相場', color='#ffff44', 
                fontsize=12, fontweight='bold', ha='center')
        ax2.text(0.9, y_position + 0.4, '売り優勢', color='#44ff44', 
                fontsize=12, fontweight='bold', ha='right')

        # ステータスとレート表示
        status = "中立相場" if 0.35 <= sentiment <= 0.65 else ("売り優勢" if sentiment > 0.65 else "買い優勢")
        color = '#ffff44' if 0.35 <= sentiment <= 0.65 else ('#44ff44' if sentiment > 0.65 else '#ff4444')
        
        ax2.text(0, y_position - 0.4,
                f'{status}\n変動率: {change_rate:+.2f}%',
                ha='center',
                color=color,
                fontsize=12,
                fontweight='bold')

        # グラフの設定
        ax2.set_xlim(-1.1, 1.1)
        ax2.set_ylim(0, 1.2)
        ax2.axis('off')

        plt.tight_layout()
        plt.savefig(save_path, dpi=100, bbox_inches='tight', 
                   facecolor='#2f3136', edgecolor='none')
        plt.close()

    @staticmethod
    def _calculate_price_sentiment(price_history) -> float:
        """変動率に基づくセンチメント計算（0=買い優勢、0.5=中立、1=売り優勢）"""
        if len(price_history) < 2:
            return 0.5
        
        current = price_history[-1].price
        previous = price_history[-2].price
        change_rate = ((current - previous) / previous) * 100
        
        # 変動率を0-1のセンチメント値に変換（範囲を制限）
        if change_rate < -1:
            return 0.15  # 買い優勢 (メーター左寄り、制限付き)
        elif change_rate > 1:
            return 0.85  # 売り優勢 (メーター右寄り、制限付き)
        else:
            # 中立域での線形変換
            normalized = (change_rate + 1) / 2  # -1%〜+1%を0〜1に変換
            return 0.35 + (normalized * 0.3)  # 0.35〜0.65の範囲に収める

    @staticmethod
    def update_price_info(price_data: PriceHistory) -> dict:
        """価格情報の更新"""
        return {
            'price': f"¥{price_data.price:,.2f}",
            'change': f"{((price_data.close - price_data.open) / price_data.open * 100):+.2f}%",
            'volume': f"{price_data.volume:,.0f} PARC",
            'market_cap': f"¥{price_data.market_cap:,.0f}"
        }

    @staticmethod
    def price_info(price_data: PriceHistory) -> Embed:
        """価格情報のEmbed作成"""
        embed = Embed(
            title="🪙 PARC 価格情報",
            color=Colour.gold() if price_data.price >= price_data.open else Colour.red(),
            timestamp=datetime.now()
        )
        
        # 価格情報（始値と現在価格で計算）
        change_percent = ((price_data.price - price_data.open) / price_data.open) * 100
        embed.add_field(
            name="💹 現在価格",
            value=f"¥ {price_data.price:,.2f}\n({change_percent:+.2f}%)",
            inline=True
        )
        
        # 追加のフィールド
        embed.add_field(
            name="📊 取引量",
            value=f"{price_data.volume:,.0f} PARC",
            inline=True
        )
        
        embed.add_field(
            name="💰 時価総額",
            value=f"¥{price_data.market_cap:,.0f}",
            inline=True
        )
        
        return embed

    @staticmethod
    def create_realtime_chart(price_history, random_price, base_price, price_range, save_path: str):
        """
        リアルタイムチャートの作成 - 普通のチャートと同じフォーマットで10秒ごとの価格を線でつなぐ
        Args:
            price_history: 価格履歴データ（DBからの1分間隔データ）
            random_price: 現在の表示価格（10秒ごとに更新）
            base_price: 基準価格
            price_range: 価格帯 {'min': 最小値, 'max': 最大値}
            save_path: 保存パス
        """
        
        # 実行時のデバッグ情報
        print(f"create_realtime_chart 実行: リアルタイム履歴データ数={len(ChartBuilder._realtime_history)}")
        
        # 現在時刻を取得
        now = datetime.now().astimezone()
        local_tz = now.tzinfo
        
        # 2段組のグラフを作成
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1])
        fig.patch.set_facecolor('#2f3136')
        
        # 上段: 価格チャート
        ax1.set_facecolor('#2f3136')
        
        # 作業用のリスト
        all_times = []
        all_prices = []
        
        # 取引時間外の場合は警告を表示
        trading_hours_active = TradingHours.is_trading_hours()
        if not trading_hours_active:
            # 次の取引開始情報を取得
            next_event_type, next_event_time = TradingHours.get_next_event()
            next_time_str = next_event_time.strftime('%H:%M')
            
            # より詳細な警告を表示
            ax1.text(0.5, 0.5, '📢 取引時間外', fontsize=30, color='white', alpha=0.7, 
                    ha='center', va='center', transform=ax1.transAxes)
            ax1.text(0.5, 0.4, '前場: 9:00～11:30 / 後場: 12:30～15:30', fontsize=16, color='white', alpha=0.7,
                    ha='center', va='center', transform=ax1.transAxes)
                    
            next_text = "前場開始" if "morning_start" in next_event_type else \
                       "後場開始" if "afternoon_start" in next_event_type else \
                       "取引終了"
            ax1.text(0.5, 0.3, f'次の{next_text}: {next_time_str}', fontsize=14, color='yellow', alpha=0.7,
                    ha='center', va='center', transform=ax1.transAxes)
        
        # == リアルタイム履歴の表示 ==
        if ChartBuilder._realtime_history and len(ChartBuilder._realtime_history) > 0:
            print(f"リアルタイムデータを使用: {len(ChartBuilder._realtime_history)}件")
            
            # 最新10分間のデータのみ使用（念のため再フィルタリング）
            cutoff_time = now - timedelta(minutes=10)
            filtered_history = [(t, p) for t, p in ChartBuilder._realtime_history if t >= cutoff_time]
            
            # リアルタイム履歴データをコピー
            all_times = [time for time, _ in filtered_history]
            all_prices = [price for _, price in filtered_history]
            
            # 最新の価格を追加（現在地点）
            all_times.append(now)
            all_prices.append(random_price)
            
            # デバッグ出力
            print(f"表示するデータ点数: {len(all_times)}件（10分間のデータ）")
            
            # データがある場合は描画
            if len(all_times) > 1:
                # 日付を数値に変換（matplotlib用）
                dates_num = mdates.date2num(all_times)
                
                # リアルタイムデータの線を描画
                for i in range(len(all_times) - 1):
                    # 各セグメントごとに色を決定
                    if all_prices[i+1] < base_price:
                        line_color = '#ff4444'  # 赤（価格が基準以下）
                    else:
                        line_color = '#44ff44'  # 緑（価格が基準以上）
                    
                    # 個別の線分を描画
                    ax1.plot([dates_num[i], dates_num[i+1]], 
                        [all_prices[i], all_prices[i+1]], 
                        '-', color=line_color, linewidth=2.5, zorder=3)
                
                # 各データポイントにマーカーを追加
                for i, (t, p) in enumerate(zip(dates_num, all_prices)):
                    is_latest = i == len(all_times) - 1
                    marker_size = 100 if is_latest else 50
                    marker_color = '#ffcc00' if is_latest else 'white'
                    edge_color = 'white' if is_latest else None
                    
                    # 点のマーカーを描画
                    ax1.scatter([t], [p], color=marker_color, s=marker_size, zorder=4, 
                            marker='o', edgecolor=edge_color, alpha=0.9)
                    
                    # 各ポイントに値段表示（最新と4つおきのポイント）
                    if is_latest or i % 4 == 0:
                        offset_y = 10 if i % 2 == 0 else -20
                        ax1.annotate(
                            f"¥{p:,.2f}",
                            xy=(t, p),
                            xytext=(0, offset_y),
                            textcoords='offset points',
                            color='white',
                            fontsize=9,
                            ha='center',
                            va='center',
                            bbox=dict(boxstyle="round,pad=0.3", fc='#333333', alpha=0.7)
                        )
                        
                        # 最新ポイントには時間も表示
                        if is_latest:
                            time_str = all_times[i].strftime("%H:%M:%S") if hasattr(all_times[i], 'strftime') else "現在"
                            ax1.annotate(
                                f"{time_str}",
                                xy=(t, p),
                                xytext=(0, -35),
                                textcoords='offset points',
                                color='white',
                                fontsize=8,
                                ha='center',
                                alpha=0.7
                            )
        else:
            print("リアルタイム履歴がありません - 空のチャートを表示")
        
        # ==== 共通の装飾設定 ====
        # 基準価格の水平線
        ax1.axhline(y=base_price, color='yellow', linestyle='--', alpha=0.5, linewidth=1.5)
        
        # 基準価格ラベル
        ax1.annotate(
            f"基準価格: ¥{base_price:,.2f}",
            xy=(mdates.date2num(now - timedelta(minutes=5)), base_price),
            xytext=(5, 0),
            textcoords='offset points',
            color='yellow',
            alpha=0.8,
            va='center'
        )
        
        # 価格帯を半透明のバンドとして表示
        ax1.axhspan(price_range['min'], price_range['max'], color='yellow', alpha=0.1)
        
        # グラフ設定
        ax1.grid(True, color='gray', alpha=0.2)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        ax1.spines['bottom'].set_color('white')
        ax1.spines['left'].set_color('white')
        ax1.tick_params(colors='white')
        
        # 凡例を追加
        ax1.legend(['リアルタイム価格'], loc='upper left', framealpha=0.7, 
                facecolor='#333333', edgecolor='none', labelcolor='white')
        
        ax1.set_title('PARC/JPY リアルタイムチャート (10分間)', color='white', fontsize=15, pad=10)
        ax1.set_ylabel('価格 (JPY)', color='white', fontsize=12)
        
        # X軸の目盛り設定
        ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))  # 1分間隔の主目盛り
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))  # 時:分 形式
        ax1.xaxis.set_minor_locator(mdates.SecondLocator(interval=10))  # 10秒間隔の副目盛り
        
        # X軸の範囲を設定（常に最新10分間を表示）
        display_start = now - timedelta(minutes=10)
        display_end = now + timedelta(seconds=30)  # 少し余白
        ax1.set_xlim(display_start, display_end)
        
        # Y軸の範囲を設定
        if all_prices:
            price_values = all_prices + [base_price, price_range['min'], price_range['max']]
            price_min = min(price_values)
            price_max = max(price_values)
            
            # 価格範囲に余白を追加
            padding = (price_max - price_min) * 0.1
            y_min = max(0, price_min - padding * 2)  # 下側により余白を持たせる
            y_max = price_max + padding
        else:
            # データがない場合は価格帯から計算
            y_min = max(0, price_range['min'] * 0.95) 
            y_max = price_range['max'] * 1.05
            
        ax1.set_ylim(y_min, y_max)
   
        
        # 下段: センチメントメーター
        ax2.set_facecolor('#2f3136')
        
        # 横軸バーの設定
        bar_height = 0.3
        y_position = 0.5
        
        # セクションの定義と描画
        sections = [
            {'range': (0.0, 0.33), 'color': '#ff4444', 'label': '買い優勢'},   # 赤
            {'range': (0.33, 0.67), 'color': '#ffff44', 'label': '中立相場'},  # 黄
            {'range': (0.67, 1.0), 'color': '#44ff44', 'label': '売り優勢'}    # 緑
        ]
        
        for section in sections:
            x_start = -1.0 + (section['range'][0] * 2)
            x_end = -1.0 + (section['range'][1] * 2)
            ax2.fill_between([x_start, x_end], 
                        y_position - bar_height/2,
                        y_position + bar_height/2,
                        color=section['color'],
                        alpha=0.3)
        
        # センチメント値の計算
        change_rate = ((random_price - base_price) / base_price) * 100
        sentiment = 0.5  # デフォルト（中立）
        if change_rate > 1:
            sentiment = min(0.8, 0.5 + change_rate / 10)  # 売り優勢（最大0.8）
        elif change_rate < -1:
            sentiment = max(0.2, 0.5 + change_rate / 10)  # 買い優勢（最小0.2）
        
        # マーカー位置の計算と描画
        marker_x = -1.0 + (sentiment * 2)
        marker_height = bar_height * 1.5
        triangle = plt.Polygon([
            [marker_x, y_position + marker_height/2],
            [marker_x - 0.05, y_position - marker_height/2],
            [marker_x + 0.05, y_position - marker_height/2]
        ], color='white')
        ax2.add_patch(triangle)
        
        # ラベル表示
        ax2.text(-0.9, y_position + 0.4, '買い優勢', color='#ff4444', 
                fontsize=12, fontweight='bold', ha='left')
        ax2.text(0, y_position + 0.4, '中立相場', color='#ffff44', 
                fontsize=12, fontweight='bold', ha='center')
        ax2.text(0.9, y_position + 0.4, '売り優勢', color='#44ff44', 
                fontsize=12, fontweight='bold', ha='right')
        
        # 変動率とステータス表示
        status = "中立相場" if abs(change_rate) <= 1 else ("売り優勢" if change_rate > 1 else "買い優勢")
        status_color = '#ffff44' if abs(change_rate) <= 1 else ('#44ff44' if change_rate > 1 else '#ff4444')
        
        # サマリー情報表示
        info_box = (
            f"{status}\n"
            f"現在値: ¥{random_price:,.2f}\n"
            f"変動率: {change_rate:+.2f}%"
        )
        
        ax2.text(0, y_position - 0.4,
                info_box,
                ha='center',
                color=status_color,
                fontsize=12,
                fontweight='bold')
        
        # グラフの設定
        ax2.set_xlim(-1.1, 1.1)
        ax2.set_ylim(0, 1.2)
        ax2.axis('off')
        
        # チャート保存前のデバッグ情報
        point_count = len(all_times)
        print(f"グラフ保存: {save_path}, データ点数={point_count}")
        plt.tight_layout()
        plt.savefig(save_path, dpi=100, bbox_inches='tight', 
                facecolor='#2f3136', edgecolor='none')
        plt.close()

def calculate_buy_sell_ratio(history: list[PriceHistory]) -> float:
    """売買比率を計算（0=強い売り、0.5=中立、1=強い買い）"""
    if not history or len(history) < 2:
        return 0.5
        
    latest = history[-1]
    prev = history[-2]
    
    # より高度な指標計算
    price_change = (latest.price - prev.price) / prev.price
    volume_change = (latest.volume - prev.volume) / (prev.volume if prev.volume > 0 else 1)
    
    # 各要素の重み付け
    price_weight = 0.7
    volume_weight = 0.3
    
    # 総合指標の計算
    indicator = (price_change * price_weight + volume_change * volume_weight)
    
    # 0から1の範囲に正規化
    return min(max((indicator + 1) / 2, 0), 1)

def calculate_market_sentiment(history) -> float:
    """市場センチメントを計算(0~1)"""
    if not history or len(history) < 2:
        return 0.5
        
    latest = history[-1]
    prev = history[-2]
    
    # 価格変動による影響(70%)
    price_change = (latest.price - prev.price) / prev.price
    
    # 取引量による影響(30%)
    volume_change = (latest.volume - prev.volume) / (prev.volume if prev.volume > 0 else 1)
    
    # 総合指標の計算
    sentiment = 0.5 + (price_change * 0.7 + volume_change * 0.3)
    
    # 0-1の範囲に収める
    return max(0, min(1, sentiment))

