import math
import random
from datetime import datetime, timedelta
from ..database.models import Transaction, PriceHistory, Wallet, User, Order
from ..utils.logger import Logger, setup_logger
from ..database.database import SessionLocal
from sqlalchemy import func, case
from ..utils.event_manager import EventManager
from sqlalchemy.orm import Session
import numpy as np
from ..utils.config import Config
import asyncio
import time
import os
import json


class PriceCalculator:
    _instance = None
    _initialized = False

    def __new__(cls, bot=None):
        if cls._instance is None:
            cls._instance = super(PriceCalculator, cls).__new__(cls)
            # クラス変数として永続フラグを一度だけ初期化
            cls._permanently_flagged_transactions = set()
        return cls._instance

    def __init__(self, bot=None):
        # インスタンス変数ではなく、クラス変数を使用するよう修正
        if not hasattr(self.__class__, '_permanently_flagged_transactions'):
            self.__class__._permanently_flagged_transactions = set()
            
        # インスタンスが既に初期化されていない場合のみ初期化
        if not PriceCalculator._initialized:
            self._initialize(bot)
            self.config = Config() # 設定ファイルの読み込み
            self.price_history = []  # 価格履歴のキャッシュ
            self.volatility_window = 24  # ボラティリティ計算期間（時間）
            self.trend_memory = []  # トレンド分析用のメモリ
            
            # 前回保存した価格状態を読み込み
            if not self._load_price_state():
                # 保存した状態がない場合はDBから最新価格を取得
                try:
                    from ..database.database import SessionLocal
                    db = SessionLocal()
                    self.set_initial_price(db)
                    db.close()
                    self.logger.info("DBから初期価格を設定しました")
                except Exception as e:
                    self.logger.error(f"DB初期価格設定エラー: {e}")

            self.market_state = 'normal'  # normal, bullish, bearish, volatile
            self.last_state_change = datetime.now()
            self.momentum_threshold = 0.02  # モメンタム閾値
            self.event_manager = bot.event_manager if bot else EventManager()

            # 市場操作検出用の変数を追加・改良
            self.detected_transactions = set()  # 検出済みの警告IDを保存
            self.detected_transaction_ids = set()  # 検出済みトランザクションIDを保存
            self.detected_addresses = {}  # 検出済みアドレスと検出時刻を保存
            self._detection_timestamps = {}  # トランザクションID: 検出時刻 のマッピング
            self.last_manipulation_warning = {}  # 最後に警告を送信した時刻（タイプ別）
            self.manipulation_cooldown = 3600  # 同じタイプの警告を再送信するまでの待機時間（秒）
            self.detection_expiry = 86400  # 検出状態の有効期間（秒）
            self.last_warnings_cleanup = datetime.now()
            # 検出済みトランザクションの価格影響を一度だけ適用
            self.applied_transaction_effects = set()  # 価格効果を既に適用したトランザクションID
            self.processed_warnings = set()  # 処理済みの警告ID（データ型別・期間別）
            # self.permanently_flagged_transactions = set()  # この行を削除または修正
            # クラス変数のフラグを読み込むだけ
            self._load_permanent_flags()
            PriceCalculator._initialized = True  # 初期化完了をマーク
            # ランダム価格を保持するリスト
            self.random_prices = []
            # 最後にランダム価格を更新した時間
            self.last_random_price_update = datetime.now()
            # ランダム価格更新間隔（秒）
            self.random_price_update_interval = 10
        else:
            # ボットの参照だけは常に最新にする
            if bot:
                self.bot = bot
                self.event_manager = bot.event_manager if hasattr(bot, 'event_manager') else self.event_manager
    @property
    def permanently_flagged_transactions(self):
        # クラス変数を返す
        if not hasattr(self.__class__, '_permanently_flagged_transactions'):
            self.__class__._permanently_flagged_transactions = set()
        return self.__class__._permanently_flagged_transactions
    @property
    def base_price(self):
        """基準価格を取得"""
        return self._base_price
    @property
    def price_range(self):
        """価格帯を取得"""
        return self._price_range

    def _initialize(self, bot=None):
        """初期化処理"""
        self.total_supply = 100_000_000
        self.launch_date = datetime(2025, 1, 1)
        self.logger = setup_logger(__name__)
        self.bot = bot
        # デフォルト価格を低い値に設定（前回の価格を保持するため）
        self._base_price = 0.07  # 100.0から0.07に変更
        self._price_range = {
            'min': 0.06,  # 90.0から0.06に変更
            'max': 0.08   # 110.0から0.08に変更
        }
        # 現在のランダム価格を保持
        self.current_random_price = self._base_price
        # 最後にランダム価格を更新した時間
        self.last_random_price_update = datetime.now()
        # ランダム価格更新間隔（秒）
        self.random_price_update_interval = 10
        # EventManagerの初期化
        self.event_manager = EventManager(bot) if bot else None
        self.logger.info(f"PriceCalculator initialized - Base Price: ¥{self._base_price:,.2f}")

    @property
    def base_price(self):
        return self._base_price

    @base_price.setter
    def base_price(self, value):
        self._base_price = float(value)

    @property
    def price_range(self):
        return self._price_range

    def set_initial_price(self, db: Session):
        """データベースから最新の価格を取得して基準価格を設定"""
        try:
            if not db:
                return

            last_price = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .first()
            
            if last_price:
                new_price = float(last_price.price)
                self._base_price = new_price
                self._price_range = {
                    'min': new_price * 0.9,
                    'max': new_price * 1.1
                }
                self.logger.info(f"前回の最終価格を基準価格として設定: ¥{self._base_price:,.2f}")
                self.logger.info(
                    f"価格帯を更新:\n"
                    f"基準価格: ¥{self._base_price:,.2f}\n"
                    f"下限: ¥{self._price_range['min']:,.2f}\n"
                    f"上限: ¥{self._price_range['max']:,.2f}"
                )

        except Exception as e:
            self.logger.error(f"初期価格の設定エラー: {str(e)}")

    def _update_price_range(self, new_price: float):
        """価格帯を更新"""
        try:
            # 基準価格を新しい価格に更新
            self._base_price = float(new_price)
            # 価格帯を±10%で設定
            self._price_range['min'] = self._base_price * 0.9
            self._price_range['max'] = self._base_price * 1.1
            self.logger.info(
                f"Price range updated:\n"
                f"Base: ¥{self._base_price:,.2f}\n"
                f"Min: ¥{self._price_range['min']:,.2f}\n"
                f"Max: ¥{self._price_range['max']:,.2f}"
            )
            
            # 価格帯が更新されたらランダム価格も更新
            self.generate_random_prices()
            
        except Exception as e:
            self.logger.error(f"Error updating price range: {e}")
            raise

    def calculate_price(self, db: Session = None) -> float:
        """価格計算"""
        try:
            self.logger.info("価格計算を開始...")
            self.logger.info(f"基準価格: ¥{self._base_price:,.2f}")
            
            # 前回価格を記録
            previous_price = self._base_price
            # 市場操作チェック
            if db:
                wash_trading_detected = self._detect_wash_trading(db)
            else:
                wash_trading_detected = False
            
            self.logger.info(f"ウォッシュトレード検出：現在の永続フラグ数: {len(self.permanently_flagged_transactions)}")
            
            # 価格変動要因の計算
            factors = {}
            
            # 価格操作が検出された場合の影響抑制
            price_suppression = 1.0
            if db:
                if wash_trading_detected:
                    # ウォッシュトレードが検出された場合、価格変動を50%抑制
                    price_suppression = 0.5
            
            # 市場深度の計算
            depth_factor = self._calculate_market_depth(db)
            factors["市場深度"] = depth_factor
            
            # サポート/レジスタンスの計算
            support_resistance = self._calculate_support_resistance(db)
            factors["価格帯"] = support_resistance
            
            # 市場心理の計算
            psychology = self._calculate_market_psychology(db)
            factors["市場心理"] = psychology
            
            # その他の要因計算
            if db:
                whale = self._calculate_whale_factor(db)
                burn = self._calculate_burn_effect(db)
                holding = self._calculate_holding_effect(db)
                mint = self._calculate_mint_impact(db)
                volume = self._calculate_transaction_effect(db)
                large_trades = self._calculate_large_trade_impact(db)
                
                factors.update({
                    "クジラ": whale,
                    "バーン効果": burn,
                    "保有効果": holding,
                    "新規発行": mint,
                    "取引量": volume,
                    "大口取引": large_trades
                })
            
            # イベントの影響
            event_change = self.event_manager.get_next_price_target() or 0.0  # None の場合は 0.0
            if event_change != 0:
                event_impact = self._calculate_event_impact(event_change)
                factors["イベント"] = event_impact
            else:
                factors["イベント"] = 1.0
                
            # 取引量が少ない場合、緩やかに価格を下げる
            inactivity_factor = self._calculate_inactivity_penalty(db)
            factors["取引不活性"] = inactivity_factor
            
            # ランダムノイズ（±1%程度）
            noise = self._calculate_market_factors()
            factors["ノイズ"] = noise
    
            # 短期的な価格変動
            short_term = self._calculate_short_term_fluctuation()
            factors["短期変動"] = short_term
            
            # 低価格時（1円以下）の上昇バイアスを追加
            low_price_bias = 1.0
            if self._base_price <= 1.0:
                # 1円以下の場合、価格が低いほど強い上昇バイアス
                bias_strength = max(0.01, min(0.05, 0.05 / self._base_price))  # 1%～5%の上昇バイアス
                low_price_bias = 1.0 + bias_strength
                self.logger.info(f"低価格上昇バイアス: +{bias_strength*100:.2f}% (×{low_price_bias:.4f})")
                factors["低価格補正"] = low_price_bias
            
            # 全要因の合成
            composite_factor = 1.0
            all_factors_unchanged = True  # すべての要因が変動なしかを確認するフラグ
            
            for factor_name, factor_value in factors.items():
                composite_factor *= factor_value
                change_percent = (factor_value - 1.0) * 100
                
                # 0以外の変動があればフラグを更新
                if abs(change_percent) > 0.01:  # 0.01%以上の変動がある
                    all_factors_unchanged = False
                    
                self.logger.info(f"{factor_name}: {change_percent:+.2f}% (×{factor_value:.4f})")
        
            
            # 価格計算
            new_price = self._base_price * composite_factor
            # すべての要因に変動がないか、変動が非常に小さい場合は強制的に変動を加える
            if all_factors_unchanged or abs(new_price - previous_price) / previous_price < 0.002:
                # 0.5%～1.5%のランダムな変動を付加
                forced_change = random.uniform(0.005, 0.015) * (-1 if random.random() < 0.5 else 1)
                new_price = previous_price * (1 + forced_change)
                self.logger.warning(f"強制的な価格変動を追加: {forced_change*100:+.2f}% (変動なし状態を防止)")
                
                # 強制変動を記録
                factors["強制変動"] = 1.0 + forced_change
            
            # 高価格帯での下落バイアス（100円以上の時）
            if self._base_price >= 100.0:
                high_price_bias = random.uniform(0.01, 0.03) * -1  # -1%～-3%のランダムな下落
                new_price = new_price * (1 + high_price_bias)
                self.logger.info(f"高価格時の下落バイアス: {high_price_bias*100:+.2f}%")
            
            # 低価格時の最低価格保証（0.01円未満にならないよう保証）
            new_price = max(new_price, 0.01)
            
            # 価格の丸め処理
            if new_price >= 1000:
                new_price = round(new_price)  # 1000円以上は整数
            elif new_price >= 100:
                new_price = round(new_price, 1)  # 100円以上は小数点第1位
            elif new_price >= 10:
                new_price = round(new_price, 2)  # 10円以上は小数点第2位
            else:
                new_price = round(new_price, 2)  # 10円未満も小数点第2位
            
            # 変動率の計算と表示
            price_change = ((new_price - self._base_price) / self._base_price) * 100
            self.logger.info(f"最終価格: ¥{new_price:,.2f} ({price_change:+.2f}%)")
            
            # 価格帯更新
            self._update_price_range(new_price)
            
            return new_price
            
        except Exception as e:
            self.logger.error(f"価格計算エラー: {e}", exc_info=True)
            return self._base_price  # エラー時は基準価格を返す

    def _calculate_market_depth(self, db: Session) -> float:
        """市場の深さ（流動性）を計算"""
        try:
            if not db:
                return 1.0

            # 注文板の厚みを計算
            orders = db.query(Order).filter(Order.status == 'pending').all()
            buy_depth = sum(o.amount for o in orders if o.side == 'buy')
            sell_depth = sum(o.amount for o in orders if o.side == 'sell')
            
            # 流動性が低いほど価格変動が大きくなる
            liquidity_ratio = min((buy_depth + sell_depth) / self.total_supply, 1)
            volatility_modifier = 1.0 + ((1 - liquidity_ratio) * 0.002)
            
            return volatility_modifier
        except Exception:
            return 1.0

    def _calculate_support_resistance(self, db: Session) -> float:
        """サポート/レジスタンスラインの影響を計算"""
        try:
            if not db:
                return 1.0

            # 過去24時間の価格を取得
            day_ago = datetime.now() - timedelta(hours=24)
            prices = db.query(PriceHistory.price)\
                .filter(PriceHistory.timestamp >= day_ago)\
                .all()

            if not prices:
                return 1.0

            prices = [p.price for p in prices]
            current = prices[0]

            # 価格の集中帯を検出
            hist, bins = np.histogram(prices, bins=20)
            support = bins[np.argmax(hist)]
            resistance = bins[np.argmax(hist) + 1]

            # サポート/レジスタンス付近での価格反発効果
            if current < support:
                return 1.005  # サポートラインでの反発
            elif current > resistance:
                return 0.995  # レジスタンスでの抵抗
            return 1.0

        except Exception:
            return 1.0

    def _calculate_market_psychology(self, db: Session) -> float:
        try:
            if not db:
                return 1.0

            # マーケットサイクルの状態遷移
            self._update_market_state()
            
            # RSIの重み付けを市場状態に応じて調整
            rsi_weight = {
                'normal': 0.03,
                'bullish': 0.04,
                'bearish': 0.04,
                'volatile': 0.02
            }[self.market_state]
            
            # RSI
            rsi_factor = self._calculate_rsi(db)
            
            # モメンタムの重み付けを調整
            momentum_weight = {
                'normal': 0.03,
                'bullish': 0.04,
                'bearish': 0.04,
                'volatile': 0.03
            }[self.market_state]
            
            momentum = self._calculate_price_momentum(db)
            
            # ボラティリティの影響を市場状態に応じて調整
            volatility_weight = {
                'normal': 0.02,
                'bullish': 0.03,
                'bearish': 0.03,
                'volatile': 0.02
            }[self.market_state]
            
            volatility = self._calculate_volatility_index(db)
            
            # 取引量の重み付け
            volume_weight = {
                'normal': 0.02,
                'bullish': 0.01,
                'bearish': 0.01,
                'volatile': 0.02
            }[self.market_state]
            
            volume = self._get_trading_volume(db)

            # 市場感情指標の計算
            sentiment = (
                (rsi_factor * rsi_weight) +
                (momentum * momentum_weight) +
                (volatility * volatility_weight) +
                (volume * volume_weight)
            )

            # トレンドメモリの更新
            self.trend_memory.append(sentiment)
            if len(self.trend_memory) > 100:  # 過去100回分を保持
                self.trend_memory.pop(0)

            # 長期トレンドの影響を追加
            long_term_trend = sum(self.trend_memory) / len(self.trend_memory)
            trend_impact = (long_term_trend - 1.0) * 0.05  # 長期トレンドの5%を反映

            # 市場状態に応じた追加調整
            state_adjustments = {
                'normal': 0.005,  # わずかな上昇バイアス
                'bullish': 0.005,  # +0.5%上昇バイアス
                'bearish': -0.001,  # -0.1%下落バイアス
                'volatile': random.uniform(-0.01, 0.015)  # より大きな変動
            }

            final_sentiment = sentiment + trend_impact + state_adjustments[self.market_state]

            # 急激な変動を抑制
            max_change = {
                'normal': 0.02,
                'bullish': 0.03,
                'bearish': 0.03,
                'volatile': 0.04
            }[self.market_state]

            return max(min(final_sentiment, 1.0 + max_change), 1.0 - max_change)

        except Exception as e:
            self.logger.error(f"市場心理計算エラー: {str(e)}")
            return 1.0

    def _update_market_state(self):
        """市場状態の更新"""
        now = datetime.now()
        state_duration = (now - self.last_state_change).total_seconds() / 3600  # 時間単位

        # 状態遷移の最小時間（時間）
        min_duration = {
            'normal': 4,
            'bullish': 2,
            'bearish': 2,
            'volatile': 1
        }

        if state_duration < min_duration[self.market_state]:
            return

        # トレンドの分析
        if len(self.trend_memory) < 10:
            return

        recent_trend = self.trend_memory[-10:]
        trend_direction = sum(1 if t > 1.0 else -1 for t in recent_trend)
        trend_strength = abs(sum(t - 1.0 for t in recent_trend))

        # 状態遷移の確率計算
        transition_prob = random.random()
        
        # 現在の状態に応じた遷移確率の調整
        if self.market_state == 'normal':
            if trend_strength > self.momentum_threshold:
                if trend_direction > 5 and transition_prob < 0.3:
                    self.market_state = 'bullish'
                elif trend_direction < -5 and transition_prob < 0.3:
                    self.market_state = 'bearish'
        elif self.market_state == 'bullish':
            if trend_direction < 0 and transition_prob < 0.4:
                self.market_state = 'normal'
            elif trend_strength > self.momentum_threshold * 2 and transition_prob < 0.2:
                self.market_state = 'volatile'
        elif self.market_state == 'bearish':
            if trend_direction > 0 and transition_prob < 0.4:
                self.market_state = 'normal'
            elif trend_strength > self.momentum_threshold * 2 and transition_prob < 0.2:
                self.market_state = 'volatile'
        elif self.market_state == 'volatile':
            if trend_strength < self.momentum_threshold and transition_prob < 0.5:
                self.market_state = 'normal'

        self.last_state_change = now

    def _calculate_large_trade_impact(self, db: Session) -> float:
        """大口取引の市場への影響を計算"""
        try:
            if not db:
                return 1.0

            # 直近1時間の大口取引を検出
            hour_ago = datetime.now() - timedelta(hours=1)
            avg_trade = db.query(func.avg(Transaction.amount))\
                .filter(Transaction.timestamp >= hour_ago)\
                .scalar() or 0
                
            large_trades = db.query(Transaction)\
                .filter(
                    Transaction.timestamp >= hour_ago,
                    Transaction.amount > avg_trade * 3
                ).all()

            if not large_trades:
                return 1.0

            # 大口取引の影響を計算
            impact = 1.0
            for trade in large_trades:
                size_factor = math.log10(trade.amount / avg_trade)
                time_factor = math.exp(-(datetime.now() - trade.timestamp).seconds / 3600)
                trade_impact = size_factor * time_factor * (0.01 if trade.transaction_type == 'buy' else -0.01)
                impact += trade_impact

            # 影響を±5%に制限
            return max(min(impact, 1.05), 0.95)

        except Exception:
            return 1.0

    def _calculate_market_factors(self) -> float:
        """市場要因の計算"""
        try:
            # ベース変動: ±0.5%に抑制
            base_change = random.uniform(-0.005, 0.005)
            
            # トレンド要因: ±0.3%
            trend = random.uniform(-0.003, 0.003)
            
            # ボラティリティ: ±0.2%
            volatility = random.uniform(-0.002, 0.002)
            
            return 1.0 + base_change + trend + volatility

        except Exception:
            return 1.0

    def _calculate_whale_factor(self, db: Session) -> float:
        """クジラ(大口保有者)の影響計算"""
        try:
            # 90%の確率で影響なし
            if random.random() > 0.1:
                return 1.0

            # 上位3アドレスの保有量を取得
            whale_holdings = db.query(func.sum(Wallet.parc_balance))\
                .order_by(Wallet.parc_balance.desc())\
                .limit(3)\
                .scalar() or 0

            # 総流通量に対する割合を計算
            total_supply = db.query(func.sum(Wallet.parc_balance)).scalar() or 1
            whale_ratio = whale_holdings / total_supply

            # クジラ係数を計算(-2%～+2%)
            return 1.0 + ((whale_ratio - 0.8) * 0.04)  # 0.04で±2%の変動になる

        except Exception:
            return 1.0

    def _calculate_supply_demand_factor(self, db) -> float:
        """需給バランスに基づく価格係数"""
        try:
            # 現在の価格トレンドを考慮
            current_trend = math.sin(time.time() / 14400) * 0.01  # 4時間周期で±1%
            
            # 24時間の取引データを取得
            day_ago = datetime.now() - timedelta(hours=24)
            buys = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.transaction_type == 'buy',
                    Transaction.timestamp >= day_ago
                ).scalar() or 0
            
            sells = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.transaction_type == 'sell',
                    Transaction.timestamp >= day_ago
                ).scalar() or 0

            if buys + sells == 0:
                return 1.0 + current_trend

            # 需給バランスを計算
            ratio = buys / (buys + sells) if (buys + sells) > 0 else 0.5
            base_effect = 0.98 + (ratio * 0.04)  # 0.98 ~ 1.02の範囲
            
            return base_effect + current_trend

        except Exception:
            return 1.0

    def _calculate_market_sentiment(self, db) -> float:
        """市場感情の計算"""
        try:
            # 直近24時間の取引を取得
            yesterday = datetime.now() - timedelta(days=1)
            buy_volume = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.timestamp >= yesterday,
                    Transaction.transaction_type == 'buy'
                ).scalar() or 0
            
            sell_volume = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.timestamp >= yesterday,
                    Transaction.transaction_type == 'sell'
                ).scalar() or 0

            # 買い優勢度を計算
            total_volume = buy_volume + sell_volume
            if total_volume == 0:
                return 1.0

            buy_ratio = buy_volume / total_volume
            # 買いが多いと上昇、売りが多いと下降
            return 1.0 + ((buy_ratio - 0.5) * 0.1)  # 最大±5%の変動

        except Exception:
            return 1.0

    def _get_market_trend(self, db) -> float:
        """市場トレンドの分析"""
        try:
            # 過去24時間の価格データを取得
            day_ago = datetime.now() - timedelta(hours=24)
            prices = db.query(PriceHistory)\
                .filter(PriceHistory.timestamp >= day_ago)\
                .order_by(PriceHistory.timestamp.asc())\
                .all()

            if not prices:
                return 1.0

            # トレンドを計算
            start_price = prices[0].price
            end_price = prices[-1].price
            trend = (end_price - start_price) / start_price

            return 1.0 + (trend * 0.1)  # トレンドの影響を10%に抑制

        except Exception:
            return 1.0

    def _get_trading_volume(self, db) -> float:
        """取引量に基づく価格係数"""
        try:
            # 24時間の取引量を取得
            day_ago = datetime.now() - timedelta(hours=24)
            volume = db.query(func.sum(Transaction.amount))\
                .filter(Transaction.timestamp >= day_ago)\
                .scalar() or 0

            # 取引量に基づく係数を計算
            volume_factor = math.log(1 + volume / 10000) / 10
            return 1.0 + volume_factor

        except Exception:
            return 1.0

    def _calculate_price_momentum(self, db) -> float:
        """価格モメンタムの計算"""
        try:
            # 直近のモメンタムを計算
            recent_prices = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .limit(5)\
                .all()

            if len(recent_prices) < 2:
                return 1.0

            momentum = sum(
                1 if p1.price > p2.price else -1
                for p1, p2 in zip(recent_prices[:-1], recent_prices[1:])
            ) / (len(recent_prices) - 1)

            return 1.0 + (momentum * 0.01)  # モメンタムの影響を1%に抑制

        except Exception:
            return 1.0

    def _calculate_moving_average(self, db) -> float:
        """移動平均の計算"""
        try:
            prices = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .limit(20)\
                .all()
                
            if len(prices) < 2:
                return 1.0

            # 5分移動平均と20分移動平均の比較
            ma5 = sum(p.price for p in prices[:5]) / 5
            ma20 = sum(p.price for p in prices) / len(prices)
            
            return 1.0 + ((ma5 / ma20 - 1) * 0.1)  # 最大10%の影響

        except Exception:
            return 1.0

    def _calculate_rsi(self, db) -> float:
        """RSIの計算"""
        try:
            prices = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .limit(14)\
                .all()

            if len(prices) < 14:
                return 1.0

            gains = []
            losses = []
            
            # 価格変動を計算
            for i in range(len(prices) - 1):
                change = prices[i].price - prices[i + 1].price
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))

            avg_gain = sum(gains) / len(gains)
            avg_loss = sum(losses) / len(losses)
            
            if avg_loss == 0:
                return 1.02  # 強気シグナル
                
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            # RSIに基づく価格係数（30-70が正常範囲）
            if rsi > 70:
                return 0.998  # 売られ過ぎ
            elif rsi < 30:
                return 1.002  # 買われ過ぎ
            else:
                return 1.0

        except Exception:
            return 1.0

    def _calculate_volatility_index(self, db) -> float:
        """ボラティリティインデックスの計算"""
        try:
            prices = db.query(PriceHistory)\
                .order_by(PriceHistory.timestamp.desc())\
                .limit(10)\
                .all()

            if len(prices) < 2:
                return 1.0

            # 価格変動の標準偏差を計算
            changes = [
                (p1.price - p2.price) / p2.price
                for p1, p2 in zip(prices[:-1], prices[1:])
            ]
            
            std_dev = np.std(changes)
            
            # ボラティリティに基づく係数を返す
            if std_dev > 0.02:  # 高ボラティリティ
                return 1.0 + (std_dev * 2)
            elif std_dev < 0.005:  # 低ボラティリティ
                return 0.995  # わずかな下落圧力
            else:
                return 1.0

        except Exception:
            return 1.0

    def _calculate_burn_effect(self, db: Session) -> float:
        """トークン燃焼の影響計算"""
        try:
            # 24時間の燃焼量を取得
            day_ago = datetime.now() - timedelta(days=1)
            burned = db.query(func.sum(Transaction.fee))\
                .filter(Transaction.timestamp >= day_ago)\
                .scalar() or 0

            # 燃焼率に基づく価格上昇効果(最大2%)
            burn_rate = burned / self.total_supply
            return 1.0 + min(burn_rate * 100, 0.02)

        except Exception:
            return 1.0

    def _calculate_holding_effect(self, db: Session) -> float:
        """保有期間と取引活性度による市場効果の計算（操作防止対策付き）"""
        try:
            now = datetime.now()
            day_ago = now - timedelta(hours=24)
            
            # クリーンアップを実行
            self._cleanup_detected_transactions()
            
            # 検出アドレスリスト
            detected_addresses_list = list(self.detected_addresses.keys())
            
            # _detection_timestampsがなければ初期化
            if not hasattr(self, '_detection_timestamps'):
                self._detection_timestamps = {}
            
            # 検出クールダウンチェック
            if "high_frequency_trading" in self.last_manipulation_warning:
                if (now - self.last_manipulation_warning["high_frequency_trading"]).total_seconds() < self.manipulation_cooldown:
                    # クールダウン中は通常の計算を行う（警告は送信しない）
                    pass
            
            # 取引件数とユニークユーザー数の両方を取得（除外条件を強化）
            transactions = db.query(func.count(Transaction.id))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 検出済みID除外
                    ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                    ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                ).scalar() or 0
                
            unique_users = db.query(func.count(func.distinct(Transaction.from_address)))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    ~Transaction.id.in_(list(self.detected_transaction_ids))  # 検出済みトランザクションを除外
                ).scalar() or 0
            
            # ユーザーごとの平均取引回数
            tx_per_user = transactions / unique_users if unique_users > 0 else 0
            
            # 操作の可能性を評価
            manipulation_score = 0
            if tx_per_user > 10:  # ユーザーあたり10回以上の取引は不自然
                manipulation_score = min((tx_per_user - 10) / 5, 1.0)  # 10回を超えると徐々にスコア上昇
                
                # 高いマニピュレーションスコアで警告を送信（クールダウンが過ぎていれば）
                should_send_warning = manipulation_score > 0.6 and self.bot
                if should_send_warning:
                    if "high_frequency_trading" not in self.last_manipulation_warning or \
                    (now - self.last_manipulation_warning["high_frequency_trading"]).total_seconds() >= self.manipulation_cooldown:
                        # 警告送信と時間記録
                        self.last_manipulation_warning["high_frequency_trading"] = now
                        
                        # 高頻度取引ユーザーを特定
                        high_frequency_users = db.query(
                            Transaction.from_address, 
                            func.count(Transaction.id).label('tx_count')
                        ).filter(
                            Transaction.timestamp >= day_ago,
                            Transaction.transaction_type.in_(['buy', 'sell'])
                        ).group_by(Transaction.from_address)\
                        .having(func.count(Transaction.id) > 10)\
                        .order_by(func.count(Transaction.id).desc())\
                        .all()
                        
                        # 関連するトランザクションを検出対象として記録
                        for addr, count in high_frequency_users:
                            # この検出に関連するトランザクションIDを取得して記録
                            recent_transactions = db.query(Transaction.id).filter(
                                Transaction.from_address == addr,
                                Transaction.timestamp >= day_ago,
                                Transaction.transaction_type.in_(['buy', 'sell'])
                            ).all()
                            
                            # トランザクションIDを記録（再検出防止）- ここを修正
                            for tx in recent_transactions:
                                self.detected_transaction_ids.add(tx.id)
                                self._detection_timestamps[tx.id] = now  # タイムスタンプを記録
                                
                            # 検出済みアドレスとして記録
                            self.detected_addresses[addr] = now
                        
                        details = (
                            f"• 検出時刻: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"• 総取引数: {transactions}件\n"
                            f"• ユニークユーザー数: {unique_users}人\n"
                            f"• ユーザーあたり平均取引数: {tx_per_user:.1f}件\n"
                            f"• 操作スコア: {manipulation_score:.2f}\n"
                            f"• 高頻度取引ユーザー数: {len(high_frequency_users)}人"
                        )
                        
                        asyncio.create_task(
                            self._send_manipulation_warning("高頻度取引操作", details)
                        )
            
            # 効果的な取引数（操作による影響を減らす）
            effective_tx = transactions / (1 + manipulation_score * 5)  # 高いマニピュレーションスコアで割引
                
            # 修正された効果計算
            if effective_tx < 1:
                return 0.998  # -0.2%
            elif effective_tx < 5:
                return 0.999  # -0.1%
            elif effective_tx < 10:
                return 1.0    # 影響なし
            elif effective_tx < 20:
                return 1.005  # +0.5%（効果半減）
            else:
                return 1.01   # +1%上昇（効果半減）

        except Exception as e:
            self.logger.error(f"保有効果計算エラー: {str(e)}")
            return 1.0

    def _calculate_mint_impact(self, db: Session) -> float:
        """新規発行のインパクト計算"""
        try:
            # 24時間の新規発行量を取得
            day_ago = datetime.now() - timedelta(days=1)
            new_mints = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type == 'mining'
                ).scalar() or 0

            # 発行量に基づく価格下落効果(最大2%)
            mint_rate = new_mints / self.total_supply
            return 1.0 + min(mint_rate * 100, 0.02)

        except Exception:
            return 1.0

    def _calculate_transaction_effect(self, db: Session) -> float:
        """取引活性度による影響計算（市場操作防止機能付き）"""
        try:
            day_ago = datetime.now() - timedelta(hours=24)
            current_time = datetime.now()
            
            # クリーンアップを実行
            self._cleanup_detected_transactions()
            
            # デバッグログ：現在の永続フラグ数を出力
            self.logger.info(f"現在の永続フラグ数: {len(self.permanently_flagged_transactions)}")
            
            # 検出アドレスリストを準備
            detected_addresses_list = list(self.detected_addresses.keys())

            # 重要: 新規取引のみを対象に計算
            # 除外条件を以下の順に適用:
            # 1. 永続的にフラグ付けされたトランザクションを除外
            # 2. 検出済み（市場操作と判定）のトランザクションIDを除外
            # 3. 既に効果を適用済みのトランザクションを除外
            # 4. 検出済みアドレスの取引を除外
            transactions = db.query(func.count(Transaction.id))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                    ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 一時検出除外
                    ~Transaction.id.in_(list(self.applied_transaction_effects)),  # 効果適用済み除外
                    ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                ).scalar() or 0
                
            # この計算で使用した通常の取引は「効果適用済み」として記録
            normal_transactions = db.query(Transaction.id)\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                    ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 一時検出除外
                    ~Transaction.id.in_(list(self.applied_transaction_effects)),  # 効果適用済み除外
                    ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                ).all()
            
            # 効果適用済みとして記録
            for tx in normal_transactions:
                self.applied_transaction_effects.add(tx.id)

            # ユニークなウォレットアドレスの数を取得（検出済みアドレスと永続フラグを除外）
            unique_wallets = db.query(func.count(func.distinct(Transaction.from_address)))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                    ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 一時検出除外
                    ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                ).scalar() or 0
                
            # 取引の平均サイズを計算（検出済みアドレスと永続フラグを除外）
            avg_transaction_size = db.query(func.avg(Transaction.amount))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                    ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 一時検出除外
                    ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                ).scalar() or 0
                
            # 小さな取引の数を取得（検出済みアドレスと永続フラグを除外）
            small_transactions = db.query(func.count(Transaction.id))\
                .filter(
                    Transaction.timestamp >= day_ago,
                    Transaction.transaction_type.in_(['buy', 'sell']),
                    Transaction.amount < avg_transaction_size * 0.5,  # 平均の半分未満の取引
                    ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                    ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 一時検出除外
                    ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                ).scalar() or 0
            
            # 取引数における小さな取引の割合
            small_tx_ratio = small_transactions / transactions if transactions > 0 else 0
            
            # 操作の可能性がある場合（小さな取引が多く、ユニークユーザーが少ない）
            manipulation_risk = small_tx_ratio > 0.7 and unique_wallets < 5 and transactions > 20
            
            # 操作リスクがある場合は影響を減らす
            if manipulation_risk:
                self.logger.warning(f"市場操作の可能性を検出: 小口取引率={small_tx_ratio:.2f}, ユニークウォレット={unique_wallets}, 総取引={transactions}")
                
                # 警告をイベントチャンネルに送信（クールダウンが過ぎていれば）
                if self.bot and (
                    "small_distributed_trading" not in self.last_manipulation_warning or 
                    (current_time - self.last_manipulation_warning["small_distributed_trading"]).total_seconds() >= self.manipulation_cooldown
                ):
                    # 小さな取引を多く行うユーザーを特定
                    small_tx_users = db.query(
                        Transaction.from_address, 
                        func.count(Transaction.id).label('tx_count')
                    ).filter(
                        Transaction.timestamp >= day_ago,
                        Transaction.transaction_type.in_(['buy', 'sell']),
                        Transaction.amount < avg_transaction_size * 0.5,  # 平均の半分未満の取引
                        ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                        ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
                    ).group_by(Transaction.from_address)\
                    .having(func.count(Transaction.id) > 5)\
                    .all()
                    
                    # 検出対象のトランザクションIDリストを作成
                    detected_tx_ids = []
                    detected_addresses = []
                    
                    # 関連するトランザクションを検出対象として記録
                    for addr, count in small_tx_users:
                        # この検出に関連するトランザクションIDを取得して記録
                        recent_transactions = db.query(Transaction.id).filter(
                            Transaction.from_address == addr,
                            Transaction.timestamp >= day_ago,
                            Transaction.transaction_type.in_(['buy', 'sell']),
                            Transaction.amount < avg_transaction_size * 0.5,  # 平均の半分未満の取引
                            ~Transaction.id.in_(list(self.permanently_flagged_transactions))  # 永続フラグ除外
                        ).all()
                        
                        # トランザクションIDをリストに追加
                        for tx in recent_transactions:
                            detected_tx_ids.append(tx.id)
                        
                        # 検出アドレスをリストに追加
                        detected_addresses.append(addr)
                    
                    if detected_tx_ids:  # 検出したトランザクションがある場合のみ警告生成
                        details = (
                            f"• 検出時刻: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"• 総取引数: {transactions}件\n"
                            f"• ユニークユーザー数: {unique_wallets}人\n"
                            f"• 小口取引率: {small_tx_ratio:.2f}\n"
                            f"• 平均取引サイズ: {avg_transaction_size:.2f} PARC\n"
                            f"• 小口取引ユーザー数: {len(small_tx_users)}人\n"
                            f"• 検出トランザクション数: {len(detected_tx_ids)}件"
                        )
                        
                        # 共通の警告生成処理を使用（永続フラグ付け含む）
                        warning_sent = self._generate_manipulation_warning(
                            "small_distributed_trading",
                            details,
                            detected_tx_ids,
                            detected_addresses
                        )
                    
                # 影響を大幅に削減（例: 通常の20%の影響に）
                effective_transactions = transactions * 0.2
            else:
                effective_transactions = transactions
                
            # 取引活性度の効果計算（修正版）
            if effective_transactions == 0:
                return 0.99  # 1%下落
            elif effective_transactions < 10:
                return 0.999  # 0.1%下落
            elif effective_transactions < 50:
                return 1.01   # 1%上昇
            else:
                return 1.02  # 2%上昇

        except Exception as e:
            self.logger.error(f"取引効果計算エラー: {str(e)}")
            return 0.99

    def _calculate_inactivity_penalty(self, db: Session) -> float:
        """取引不活性によるペナルティ計算（操作防止対策付き）"""
        try:
            hours_ago = datetime.now() - timedelta(hours=6)
            
            # 取引件数とユニークユーザー数の両方を取得
            transaction_count = db.query(func.count(Transaction.id))\
                .filter(
                    Transaction.timestamp >= hours_ago,
                    Transaction.transaction_type.in_(['buy', 'sell'])
                ).scalar() or 0
                
            unique_users = db.query(func.count(func.distinct(Transaction.from_address)))\
                .filter(
                    Transaction.timestamp >= hours_ago,
                    Transaction.transaction_type.in_(['buy', 'sell'])
                ).scalar() or 0
                
            # 取引量も考慮
            total_volume = db.query(func.sum(Transaction.amount))\
                .filter(
                    Transaction.timestamp >= hours_ago,
                    Transaction.transaction_type.in_(['buy', 'sell'])
                ).scalar() or 0
                
            # 複合指標を作成（ユニークユーザー数と取引量の両方を考慮）
            activity_score = (unique_users * 2 + transaction_count) / 3 
            
            # 修正された不活性ペナルティ計算
            if activity_score < 1:
                return 0.985  # 1.5%下落
            elif activity_score < 2:
                return 0.992  # 0.8%下落
            elif activity_score < 3:
                return 0.995  # 0.5%下落
            elif activity_score < 5:
                return 0.998  # 0.2%下落
            elif activity_score < 8:
                return 1.0    # 変化なし
            else:
                return 1.002  # 0.2%上昇
                
        except Exception:
            return 0.999  # エラー時は0.1%下落

    def _update_base_price(self, new_price: float):
        """基準価格を更新（後方互換性のため）"""
        self._update_price_range(new_price)
        self.logger.info(f"Base price updated (legacy method) to: ¥{new_price:,.2f}")

    def _calculate_event_impact(self, event_change: float) -> float:
        """イベントの影響を計算"""
        try:
            if event_change is None:
                return 1.0
                
            # イベント効果を制限（過剰影響防止）
            effect = 1.0 + (event_change / 100)  # イベントの影響を適用
            # イベント進捗のログ表示
            if self.bot and self.event_manager and self.event_manager.current_event:
                event = self.event_manager.current_event
                total_steps = event.get('total_steps', len(self.event_manager.remaining_effects) + 1)
                current_step = total_steps - len(self.event_manager.remaining_effects)
                
                self.logger.info(
                    f"イベント進捗: {event['name']}\n"
                    f"⚡ 変動: {event_change:+.2f}%\n"
                    f"📊 進捗: {current_step}/{total_steps}\n"
                    f"💫 残り影響回数: {len(self.event_manager.remaining_effects) - 1}\n"
                    f"📈 合計変動目標: {event['total_change']:+.2f}%"
                )
                
                # イベント効果の適用後、該当部分を除去
                if self.event_manager.remaining_effects:
                    self.event_manager.remaining_effects.pop(0)
                
                # イベント終了時の通知
                if not self.event_manager.remaining_effects:
                    asyncio.create_task(
                        self.event_manager._notify_event(event, is_final=True)
                    )
                    self.logger.info(
                        f"🏁 イベント終了: {event['name']}\n"
                        f"📊 最終変動率: {event['total_change']:+.2f}%"
                    )
                    self.event_manager.current_event = None

            return effect

        except Exception as e:
            self.logger.error(f"イベント影響計算エラー: {str(e)}")
            return 1.0

    def _calculate_noise_factor(self) -> float:
        """市場ノイズの計算（小さなランダム変動）"""
        # ノイズ幅を拡大：-0.8%から+0.8%のランダムなノイズ
        noise = random.uniform(-0.008, 0.008)
        
        # 価格帯に応じたノイズ調整
        if self._base_price >= 100.0:
            # 高価格帯ではノイズが下方にバイアス
            noise = noise * 1.2 - 0.002  # 最大-1.0%, 最小+0.6%
        elif self._base_price <= 1.0:
            # 低価格帯ではノイズが上方にバイアス
            noise = noise * 1.2 + 0.002  # 最小-0.6%, 最大+1.0%
        
        # より細かい変動を追加
        micro_noise = random.uniform(0.003, 0.006)
        return 1.0 + noise + micro_noise

    def _calculate_short_term_fluctuation(self) -> float:
        """短期的な価格変動の計算"""
        try:
            # 高価格時の下落バイアスを追加
            high_price_factor = 1.0
            if self._base_price >= 100.0:
                # 100円以上の場合は下落バイアス強化
                high_price_factor = 0.3  # 下落確率を増加させる
            
            # 低価格時の調整
            low_price_factor = 1.0
            if self._base_price <= 1.0:
                # 1円以下の場合は上昇バイアス強化
                low_price_factor = 0.5  # 下振れをさらに半減
            
            # 基本変動を調整（高価格時は下方に、低価格時は上方にバイアス）
            if self._base_price >= 100.0:
                base_min = -0.02  # 高価格時は下振れを強化
                base_max = 0.005
            else:
                # 通常の場合の変動幅を拡大
                base_min = -0.015 * low_price_factor  # 低価格時は下振れが小さくなる
                base_max = 0.012 * (2.0 - low_price_factor)  # 低価格時は上振れが大きくなる
            
            base_fluctuation = random.uniform(base_min, base_max)
            
            # 急激な変動（スパイク）の確率と方向性を価格帯に応じて調整
            spike_chance = 0.12  # 基本確率を増加（8% → 12%）
            
            # 高価格時は下落スパイク、低価格時は上昇スパイクが出やすいように調整
            if self._base_price >= 100.0:
                up_chance = 0.3  # 高価格時は下落スパイクが出やすい (30%の確率で上昇)
            elif self._base_price <= 1.0:
                up_chance = min(0.85, 0.7 + (1.0 - self._base_price) * 0.15)  # 低価格時は上昇確率アップ
            else:
                up_chance = 0.5  # 通常時は50%の確率で上昇

            # スパイク強度も価格帯に応じて調整
            if random.random() < spike_chance:
                if random.random() < up_chance:
                    # 上昇スパイク
                    spike = random.uniform(0.002, 0.015)  # +0.2%～+1.5%
                else:
                    # 下落スパイク
                    spike = random.uniform(-0.025, -0.008)  # -2.5%～-0.8%
                base_fluctuation += spike

            # 周期変動の振幅を拡大
            time_now = time.time()
            short_cycle = math.sin(time_now / 1800) * 0.008  # ±0.8%
            medium_cycle = math.cos(time_now / 7200) * 0.012  # ±1.2%
            long_cycle = math.sin(time_now / 28800) * 0.015  # ±1.5%

            # ランダムな上昇バイアスを調整
            up_bias_chance = 0.4  # 基本確率を40%に引き上げ
            up_bias_max = 0.008  # 最大0.8%の上昇バイアス
            
            if self._base_price <= 1.0:
                up_bias_chance = min(0.6, 0.4 + (1.0 - self._base_price) * 0.2)  # 最大60%の確率
                up_bias_max = min(0.015, 0.008 + (1.0 - self._base_price) * 0.007)  # 最大1.5%の上昇
            elif self._base_price >= 100.0:
                # 高価格時は下落バイアスを追加
                up_bias_chance = 0.2  # 20%の確率で上昇バイアス
                down_bias_chance = 0.5  # 50%の確率で下落バイアス
                
                if random.random() < down_bias_chance:
                    down_bias = -random.uniform(0.005, 0.015)  # -0.5%～-1.5%の下落バイアス
                    base_fluctuation += down_bias
            
            if random.random() < up_bias_chance:
                up_bias = random.uniform(0, up_bias_max)
            else:
                up_bias = 0

            return 1.0 + base_fluctuation + short_cycle + medium_cycle + long_cycle + up_bias
            
        except Exception as e:
            self.logger.error(f"短期変動計算エラー: {e}")
            return 1.0

    async def _send_manipulation_warning(self, manipulation_type: str, details: str):
        """市場操作の警告をイベントチャンネルに送信"""
        try:
            if not self.bot:
                self.logger.warning("Botが設定されていないため警告を送信できません")
                return

            # 重複警告防止のための確認
            current_time = datetime.now()
            
            # 時間ベースのキー (時間単位)
            time_key = f"{manipulation_type}_{current_time.strftime('%Y%m%d%H')}"
            
            # 内容ベースのキー (警告の詳細から特徴を抽出)
            features = self._extract_warning_features(details)
            content_hash = hash(str(sorted(features.items())))
            content_key = f"{manipulation_type}_{content_hash}_{current_time.strftime('%Y%m%d')}"
            
            # 両方のキーで重複チェック - 特に時間キーは同じ時間範囲で同じ種類の警告を防止
            if time_key in self.processed_warnings or content_key in self.processed_warnings:
                self.logger.info(f"重複警告のため送信をスキップ: {manipulation_type}")
                return

            # 処理済み記録を追加 (両方のキーを記録)
            self.processed_warnings.add(time_key)
            self.processed_warnings.add(content_key)
            
            self.logger.info(f"市場操作警告を送信: {manipulation_type}")
        
            
            from ..utils.embed_builder import EmbedBuilder
            
            # 警告Embedを作成
            embed = EmbedBuilder.market_manipulation_warning(manipulation_type, details)
            
            # イベントチャンネルに送信 - チャンネルが見つからない場合の処理を強化
            try:
                if not hasattr(self.config, 'event_channel_id'):
                    self.logger.error("イベントチャンネルIDが設定されていません")
                    return
                    
                channel_id = self.config.event_channel_id
                
                # チャンネル取得を試みる
                channel = None
                try:
                    channel = self.bot.get_channel(int(channel_id))
                except Exception:
                    self.logger.warning(f"チャンネルID変換エラー: {channel_id}")
                    
                if channel:
                    await channel.send(embed=embed)
                    self.logger.info(f"イベントチャンネル({channel_id})に警告を送信しました")
                else:
                    # チャンネルが見つからない場合はフェッチを試みる
                    try:
                        channel = await self.bot.fetch_channel(int(channel_id))
                        if channel:
                            await channel.send(embed=embed)
                            self.logger.info(f"フェッチしたチャンネル({channel_id})に警告を送信しました")
                        else:
                            self.logger.error(f"チャンネルが見つかりません: {channel_id}")
                    except Exception as e:
                        self.logger.error(f"チャンネルフェッチエラー: {str(e)}")
            except Exception as e:
                self.logger.error(f"イベントチャンネル送信エラー: {str(e)}", exc_info=True)
        

            # 管理者にDMでも通知
            try:
                if hasattr(self.config, 'admin_user_id') and self.config.admin_user_id:
                    admin_user = await self.bot.fetch_user(int(self.config.admin_user_id))
                    if admin_user:
                        await admin_user.send(embed=embed)
                        self.logger.info(f"管理者({self.config.admin_user_id})にDM送信しました")
            except Exception as e:
                self.logger.error(f"管理者DM送信エラー: {str(e)}")

        except Exception as e:
            self.logger.error(f"市場操作警告送信エラー: {str(e)}", exc_info=True)

    def _detect_wash_trading(self, db: Session) -> bool:
        """ウォッシュトレード（自己売買操作）の検出"""
        try:
            # クリーンアップを実行
            self._cleanup_detected_transactions()

            # クールダウンチェック
            if self._is_in_cooldown("wash_trading"):
                return False

            # 3時間以内の取引を確認
            hours_ago = datetime.now() - timedelta(hours=3)
            current_time = datetime.now()

            # デバッグログ：現在の永続フラグ数を出力
            self.logger.info(f"ウォッシュトレード検出：現在の永続フラグ数: {len(self.permanently_flagged_transactions)}")
            if self.permanently_flagged_transactions:
                self.logger.debug(f"永続フラグID一覧: {list(self.permanently_flagged_transactions)[:5]}... 他{len(self.permanently_flagged_transactions)-5}件")

            # 検出アドレスリストを準備
            detected_addresses_list = list(self.detected_addresses.keys())

            # アドレスごとの買い取引と売り取引の量を集計
            # 以下の順に除外条件を適用:
            # 1. 永続的にフラグ付けされたトランザクションを除外
            # 2. 検出済み（市場操作と判定）のトランザクションIDを除外
            # 3. 検出済みアドレスの取引を除外
            address_stats = db.query(
                Transaction.from_address,
                func.sum(case((Transaction.transaction_type == 'buy', Transaction.amount), else_=0)).label('buy_amount'),
                func.sum(case((Transaction.transaction_type == 'sell', Transaction.amount), else_=0)).label('sell_amount'),
                func.count(Transaction.id).label('tx_count')
            ).filter(
                Transaction.timestamp >= hours_ago,
                Transaction.transaction_type.in_(['buy', 'sell']),
                ~Transaction.id.in_(list(self.permanently_flagged_transactions)),  # 永続フラグ除外
                ~Transaction.id.in_(list(self.detected_transaction_ids)),  # 一時検出除外
                ~Transaction.from_address.in_(detected_addresses_list) if detected_addresses_list else True  # 検出済みアドレス除外
            ).group_by(Transaction.from_address).all()
            
            # ウォッシュトレードの可能性がある取引を検出
            for addr, buy_amount, sell_amount, tx_count in address_stats:
                # 同一アドレスが短時間に多数の売買を行っている場合
                if tx_count > 10 and buy_amount > 0 and sell_amount > 0:
                    # 売買金額の差が小さい場合はウォッシュトレードの可能性
                    ratio = min(buy_amount, sell_amount) / max(buy_amount, sell_amount)
                    if ratio > 0.7:  # 70%以上の売買一致率
                        self.logger.debug(f"ウォッシュトレード検出候補 - アドレス: {addr}, 購入量: {buy_amount:.2f}, 売却量: {sell_amount:.2f}, 比率: {ratio:.2f}")
                        # 関連するトランザクションIDを取得（永続フラグを除外）
                        recent_transactions = db.query(Transaction.id).filter(
                            Transaction.from_address == addr,
                            Transaction.timestamp >= hours_ago,
                            Transaction.transaction_type.in_(['buy', 'sell']),
                            ~Transaction.id.in_(list(self.permanently_flagged_transactions))  # 永続フラグを除外
                        ).all()
                        
                        # 取得したトランザクションIDをリスト化
                        tx_ids = [tx.id for tx in recent_transactions]
                        
                        # 検出対象のトランザクションがない場合はスキップ
                        if not tx_ids:
                            self.logger.info(f"アドレス {addr} はウォッシュトレードの疑いがありますが、未検出のトランザクションが見つかりません")
                            continue
                        
                        # ユーザー情報取得
                        user = db.query(User).join(Wallet).filter(Wallet.address == addr).first()
                        user_id = user.discord_id if user else "不明"
                        
                        # 警告詳細の作成
                        details = (
                            f"• ユーザーID: {user_id}\n"
                            f"• ウォレットアドレス: {addr}\n"
                            f"• 検出時刻: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"• 取引回数: {tx_count}回\n"
                            f"• 購入量: {buy_amount:.2f} PARC\n"
                            f"• 売却量: {sell_amount:.2f} PARC\n"
                            f"• 売買一致率: {ratio:.2f}\n"
                            f"• 検出トランザクション数: {len(tx_ids)}件"
                        )
                        
                        # 共通の警告生成処理を使用
                        warning_sent = self._generate_manipulation_warning(
                            "wash_trading",
                            details,
                            tx_ids,
                            [addr]
                        )
                        
                        # 警告が実際に送信された場合のみTrueを返す
                        if warning_sent:
                            self.logger.warning(f"ウォッシュトレード検出: アドレス {addr} の {len(tx_ids)} 件のトランザクションをフラグ付けしました")
                            return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"ウォッシュトレード検出エラー: {str(e)}")
            return False

    def _cleanup_detected_transactions(self):
        """古い検出データをクリーンアップ"""
        try:
            current_time = datetime.now()
            
            # 最後のクリーンアップから1時間以上経過している場合のみ実行
            if hasattr(self, 'last_warnings_cleanup') and \
            (current_time - self.last_warnings_cleanup).total_seconds() < 3600:
                return
            
            # permanently_flagged_transactions はクリーンアップしない（永続的に維持）
            
            # 長期間経過したトランザクションの効果適用フラグをクリア（週に1回程度）
            if random.random() < 0.05:  # 5%の確率で実行（負荷軽減のため）
                self.applied_transaction_effects = set()
                self.logger.info("適用済み効果トランザクションIDをリセットしました")

            # _detection_timestampsがなければ初期化
            if not hasattr(self, '_detection_timestamps'):
                self._detection_timestamps = {}

            # 期限切れのトランザクションIDを特定
            expired_ids = []
            for tx_id, timestamp in self._detection_timestamps.items():
                if (current_time - timestamp).total_seconds() >= self.detection_expiry:
                    expired_ids.append(tx_id)
            
            # 期限切れのIDをセットから削除
            for tx_id in expired_ids:
                if tx_id in self.detected_transaction_ids:
                    self.detected_transaction_ids.remove(tx_id)
                if tx_id in self._detection_timestamps:
                    del self._detection_timestamps[tx_id]
                    
            # 期限切れのアドレスも削除
            expired_addresses = []
            for addr, timestamp in self.detected_addresses.items():
                if (current_time - timestamp).total_seconds() >= self.detection_expiry:
                    expired_addresses.append(addr)
                    
            for addr in expired_addresses:
                if addr in self.detected_addresses:
                    del self.detected_addresses[addr]
                    
            # 処理済み警告のクリーンアップを改善
            day_ago = current_time - timedelta(days=3)  # 3日前
            old_warnings = set()
            for warning_id in self.processed_warnings:
                try:
                    if '_' in warning_id:
                        parts = warning_id.split('_')
                        if len(parts) >= 2:
                            # 時間ベースのキーの場合（YYYYMMDDHHフォーマット）
                            if parts[1].isdigit() and len(parts[1]) >= 8:
                                date_str = parts[1][:8]  # YYYYMMDDの部分を取得
                                warning_date = datetime.strptime(date_str, '%Y%m%d')
                                if warning_date < day_ago:
                                    old_warnings.add(warning_id)
                            # ハッシュベースのキーの場合はタイムスタンプを確認
                            elif len(parts) >= 3 and parts[2].isdigit():
                                date_str = parts[2][:8]  # YYYYMMDDの部分
                                warning_date = datetime.strptime(date_str, '%Y%m%d')
                                if warning_date < day_ago:
                                    old_warnings.add(warning_id)
                except Exception:
                    continue
                    
            # 古い処理済み警告を削除
            for warning_id in old_warnings:
                if warning_id in self.processed_warnings:
                    self.processed_warnings.remove(warning_id)
                
            self.last_warnings_cleanup = current_time
            if expired_ids or expired_addresses or old_warnings:
                self.logger.info(
                    f"検出データクリーンアップ完了: {len(expired_ids)}件のトランザクション、"
                    f"{len(expired_addresses)}件のアドレス、{len(old_warnings)}件の警告IDを削除"
                )
            
        except Exception as e:
            self.logger.error(f"検出データクリーンアップエラー: {str(e)}")

    def _detect_manipulation(self, transaction_data, manipulation_type):
        """操作検出の共通処理"""
        detected = False
        # 検出条件に基づいて判定...
        
        if detected:
            # 検出結果を記録
            for tx_id in transaction_data.get('transaction_ids', []):
                self.detected_transaction_ids.add(tx_id)
                self._detection_timestamps[tx_id] = datetime.now()
                
            # 送信すべき警告があるか判定
            should_send_warning = (
                manipulation_type not in self.last_manipulation_warning or
                (datetime.now() - self.last_manipulation_warning[manipulation_type]).total_seconds() >= self.manipulation_cooldown
            )
            
            if should_send_warning and self.bot:
                # 警告送信をキュー
                warning_details = transaction_data.get('details', '')
                asyncio.create_task(
                    self._send_manipulation_warning(manipulation_type, warning_details)
                )
                self.last_manipulation_warning[manipulation_type] = datetime.now()
        
        return detected

    def _is_in_cooldown(self, manipulation_type: str) -> bool:
        """同種の警告がクールダウン中かどうかを判定"""
        current_time = datetime.now()
        
        if manipulation_type in self.last_manipulation_warning:
            elapsed = (current_time - self.last_manipulation_warning[manipulation_type]).total_seconds()
            if elapsed < self.manipulation_cooldown:
                self.logger.info(f"クールダウン中のため{manipulation_type}の検出をスキップ ({elapsed:.1f}/{self.manipulation_cooldown}秒)")
                return True

        return False

    def _generate_manipulation_warning(self, manipulation_type: str, details: str, transaction_ids: list, addresses: list) -> bool:
        """操作検出時の警告生成を一元化"""
        try:
            # 1. クールダウンチェック
            current_time = datetime.now()
            if manipulation_type in self.last_manipulation_warning:
                elapsed = (current_time - self.last_manipulation_warning[manipulation_type]).total_seconds()
                if elapsed < self.manipulation_cooldown:
                    self.logger.info(f"{manipulation_type}警告はクールダウン中 ({elapsed:.1f}/{self.manipulation_cooldown}秒)")
                    return False

            # 2. 検出済みとして記録
            self.last_manipulation_warning[manipulation_type] = current_time

            # 永続フラグの状態を確認
            self.logger.debug(f"永続フラグ追加前 - クラス変数: {len(self.__class__._permanently_flagged_transactions)}件, プロパティ: {len(self.permanently_flagged_transactions)}件")
            
            # 既に永続フラグ付けされているトランザクションかどうかをチェック
            already_flagged = set(str(tx_id) for tx_id in transaction_ids).intersection(self.permanently_flagged_transactions)
            if already_flagged:
                self.logger.info(f"{len(already_flagged)}件のトランザクションは既にフラグ付け済みのため、再検出をスキップします")
                return False

            # デバッグ: トランザクションIDのリストを表示
            self.logger.debug(f"フラグに追加するID: {transaction_ids[:5] if len(transaction_ids) > 5 else transaction_ids}")
            
            # 3. トランザクションIDを記録（一時的な検出と永続的なフラグ付けの両方）
            before_count = len(self.permanently_flagged_transactions)
            
            for tx_id in transaction_ids:
                # 文字列に変換して一貫性を保証
                str_tx_id = str(tx_id)
                self.detected_transaction_ids.add(str_tx_id)
                self._detection_timestamps[str_tx_id] = current_time
                # クラス変数に直接アクセス
                self.__class__._permanently_flagged_transactions.add(str_tx_id)  # 永続的にフラグ付け
            
            after_count = len(self.permanently_flagged_transactions)
            added_count = after_count - before_count
            
            self.logger.debug(f"永続フラグに追加した後: クラス変数={len(self.__class__._permanently_flagged_transactions)}件, プロパティ={len(self.permanently_flagged_transactions)}件")
            self.logger.debug(f"追加件数: {added_count}件 (期待: {len(transaction_ids)}件)")

            self.logger.info(f"{manipulation_type}: {added_count}件のトランザクションを永続的にフラグ付けしました")

            # 永続フラグが更新されたら即座に保存
            self._save_permanent_flags()

            # 4. アドレスを記録
            for addr in addresses:
                self.detected_addresses[addr] = current_time

            # 5. 警告送信
            if self.bot:
                asyncio.create_task(
                    self._send_manipulation_warning(manipulation_type, details)
                )
            
            return True
        except Exception as e:
            self.logger.error(f"操作警告生成エラー: {str(e)}", exc_info=True)
            return False

    def _extract_warning_features(self, details: str) -> dict:
        """警告の詳細から特徴量を抽出し、重複検出に使用する"""
        features = {}
        
        # 詳細テキストから重要な特徴を抽出
        try:
            lines = details.split('\n')
            for line in lines:
                if '•' in line:
                    key_value = line.split('•')[1].strip()
                    if ':' in key_value:
                        key, value = key_value.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        features[key] = value
        except Exception:
            # 抽出に失敗しても処理を続行
            pass
        
        return features

    def _load_permanent_flags(self):
        """永続的なフラグリストを読み込む"""
        try:
            # カレントディレクトリをチェック
            if os.path.isdir("data"):
                flag_file = 'data/permanent_flags.json'
            else:
                # 相対パスでも見つからない場合は絶対パスを試す
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                flag_file = os.path.join(base_dir, 'data', 'permanent_flags.json')
                os.makedirs(os.path.dirname(flag_file), exist_ok=True)
            
            if os.path.exists(flag_file):
                with open(flag_file, 'r') as f:
                    data = json.load(f)
                    # すべての要素を文字列として扱う
                    tx_list = [str(tx) for tx in data.get('transactions', [])]
                    
                    # クラス変数に直接設定する（プロパティではなく）
                    self.__class__._permanently_flagged_transactions = set(tx_list)
                    self.logger.info(f"{len(self.__class__._permanently_flagged_transactions)}件の永続的にフラグ付けされたトランザクションを読み込みました")
                    
                    # 読み込んだ内容を表示（デバッグ用）
                    if self.__class__._permanently_flagged_transactions:
                        sample = list(self.__class__._permanently_flagged_transactions)[:3]
                        self.logger.debug(f"読み込みサンプル: {sample}")
            else:
                self.logger.info(f"永続フラグファイル {flag_file} が見つかりません。新規に作成します。")
        except Exception as e:
            self.logger.error(f"永続的フラグの読み込みエラー: {str(e)}")

    def _save_permanent_flags(self):
        """永続的なフラグリストを保存する"""
        try:
            # 保存前のデバッグ情報
            pft = getattr(self.__class__, '_permanently_flagged_transactions', set())
            self.logger.info(f"保存前デバッグ: クラス変数内の永続フラグ数: {len(pft)}")
            
            # ファイルパスの解決
            if os.path.isdir("data"):
                flag_file = 'data/permanent_flags.json'
            else:
                # 相対パスでも見つからない場合は絶対パスを試す
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                flag_dir = os.path.join(base_dir, 'data')
                os.makedirs(flag_dir, exist_ok=True)
                flag_file = os.path.join(flag_dir, 'permanent_flags.json')
            
            # すべての要素を文字列として保存
            tx_list = [str(tx) for tx in self.permanently_flagged_transactions]
            
            # ファイルに保存
            with open(flag_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'transactions': tx_list
                }, f, ensure_ascii=False, indent=2)
                
            self.logger.info(f"{len(tx_list)}件の永続的にフラグ付けされたトランザクションを保存しました: {flag_file}")
            
            # 保存内容を表示（デバッグ用）
            if tx_list:
                sample = tx_list[:min(3, len(tx_list))]
                self.logger.debug(f"保存サンプル: {sample}")
                
        except Exception as e:
            self.logger.error(f"永続的フラグの保存エラー: {str(e)}", exc_info=True)

    def _test_permanent_flags(self):
        """永続フラグの保存/読込処理をテスト"""
        try:
            # テストIDを追加
            test_id = f"test_{int(time.time())}"
            self.__class__._permanently_flagged_transactions.add(test_id)
            
            # 保存前のカウント
            before_save = len(self.permanently_flagged_transactions)
            self.logger.info(f"保存前のフラグ数: {before_save}件")
            
            # 保存
            self._save_permanent_flags()
            
            # 現在のセットをクリア (読込テスト用)
            old_set = self.__class__._permanently_flagged_transactions.copy()
            self.__class__._permanently_flagged_transactions.clear()
            
            # 読み込み
            self._load_permanent_flags()
            after_load = len(self.permanently_flagged_transactions)
            
            self.logger.info(f"読込後のフラグ数: {after_load}件")
            
            # 以前の状態に戻す
            if after_load != before_save:
                self.__class__._permanently_flagged_transactions = old_set
                self._save_permanent_flags()
                self.logger.warning("フラグの保存/読込でカウントが一致しないため元に戻しました")
            
        except Exception as e:
            self.logger.error(f"永続フラグテストエラー: {str(e)}", exc_info=True)

    def generate_random_price(self):
        """指定した価格帯内で単一のランダム価格を生成"""
        try:
            # 変動幅を±5%に制限する
            max_variation = 0.05  # 5%
            min_price = max(self._base_price * (1 - max_variation), self._price_range['min'])
            max_price = min(self._base_price * (1 + max_variation), self._price_range['max'])
            
            # 基本価格を中心にした重み付きランダム分布を作成
            base_weight = 0.5  # 中心付近に価格が集まる確率
            
            # 重み付きランダム選択（中心に近い価格が出やすい）
            if random.random() < base_weight:
                # 中心付近の価格
                price = self._base_price + random.uniform(-0.03, 0.03) * self._base_price
            else:
                # 範囲全体でのランダム価格
                price = random.uniform(min_price, max_price)
            
            # 価格を範囲内に制限
            price = max(min(price, max_price), min_price)
            # 小数点以下2桁に丸める
            price = round(price, 2)
            
            self.current_random_price = price
            self.last_random_price_update = datetime.now()
            
            self.logger.debug(f"ランダム価格を生成: {price}")
            return price
            
        except Exception as e:
            self.logger.error(f"ランダム価格生成エラー: {e}")
            # エラーの場合は基本価格を中心に小さな変動を持つ価格を生成
            return round(self._base_price * (1 + random.uniform(-0.01, 0.01)), 2)

    def get_current_random_price(self):
        """現在のランダム価格を取得（必要に応じて更新）"""
        now = datetime.now()
        if not self.random_prices or (now - self.last_random_price_update).total_seconds() >= self.random_price_update_interval:
            self.generate_random_prices()
        
        # ランダムな価格を1つ選択
        return random.choice(self.random_prices) if self.random_prices else self._base_price

    def get_all_random_prices(self):
        """すべてのランダム価格を取得（必要に応じて更新）"""
        now = datetime.now()
        if not self.random_prices or (now - self.last_random_price_update).total_seconds() >= self.random_price_update_interval:
            self.generate_random_prices()
        
        return self.random_prices
    
    def generate_random_prices(self, count=5):
        """指定した価格帯内で複数のランダム価格を生成"""
        try:
            # 変動幅を拡大（±5%→±7%）
            max_variation = 0.07
            min_price = max(self._base_price * (1 - max_variation), self._price_range['min'])
            max_price = min(self._base_price * (1 + max_variation), self._price_range['max'])
            
            # 高価格時は下落バイアス、低価格時は上昇バイアスを加える
            if self._base_price >= 100.0:
                # 下落バイアス（中心をやや下に）
                center_bias = -0.02  # -2%バイアス
            elif self._base_price <= 1.0:
                # 上昇バイアス
                center_bias = 0.02   # +2%バイアス
            else:
                center_bias = 0.0   # バイアスなし
                
            # 複数の価格を生成
            prices = []
            for _ in range(count):
                # 基本価格を中心にした重み付きランダム分布を作成
                base_weight = 0.5  # 中心付近に価格が集まる確率
                
                # 重み付きランダム選択（中心に近い価格が出やすい）
                if random.random() < base_weight:
                    # 中心付近の価格（バイアス付き）
                    biased_center = self._base_price * (1 + center_bias)
                    price = biased_center + random.uniform(-0.04, 0.04) * self._base_price
                else:
                    # 範囲全体でのランダム価格
                    price = random.uniform(min_price, max_price)
                
                # 価格を範囲内に制限
                price = max(min(price, max_price), min_price)
                # 小数点以下2桁に丸める
                price = round(price, 2)
                prices.append(price)
            
            # 最新のランダム価格を更新
            self.random_prices = prices
            self.last_random_price_update = datetime.now()
            
            # 単一の現在価格も更新（ランダムリストの中から選ぶ）
            self.current_random_price = random.choice(prices)
            
            self.logger.debug(f"{count}個のランダム価格を生成: {prices}")
            return prices
            
        except Exception as e:
            self.logger.error(f"ランダム価格生成エラー: {e}")
            # エラーの場合は基本価格を中心に小さな変動を持つ価格リストを生成
            fallback_prices = [round(self._base_price * (1 + random.uniform(-0.01, 0.01)), 2) for _ in range(count)]
            self.random_prices = fallback_prices
            self.current_random_price = fallback_prices[0]
            return fallback_prices

    def get_latest_random_price(self) -> float:
        """最新のランダム価格を取得する（なければ現在の基本価格を返す）"""
        if hasattr(self, 'current_random_price') and self.current_random_price:
            return self.current_random_price
        return self._base_price

    def get_price_range_for_trading(self) -> dict:
        """取引用の価格情報を返す"""
        current = self.get_latest_random_price()
        return {
            'current': current,
            'base': self._base_price,
            'min': self._price_range['min'],
            'max': self._price_range['max'],
            'change': ((current - self._base_price) / self._base_price) * 100
        }

    def _save_price_state(self):
        """現在の価格状態をファイルに保存"""
        try:
            price_state_file = "data/price_state.json"
            os.makedirs(os.path.dirname(price_state_file), exist_ok=True)
            
            state_data = {
                "base_price": self._base_price,
                "min_price": self._price_range['min'],
                "max_price": self._price_range['max'],
                "saved_at": datetime.now().isoformat()
            }
            
            with open(price_state_file, "w") as f:
                json.dump(state_data, f, indent=2)
                
            self.logger.info(f"価格状態を保存しました: ¥{self._base_price:,.2f}")
        except Exception as e:
            self.logger.error(f"価格状態の保存エラー: {e}")

    def _load_price_state(self):
        """保存された価格状態を読み込む"""
        try:
            price_state_file = "data/price_state.json"
            if os.path.exists(price_state_file):
                with open(price_state_file, "r") as f:
                    price_state = json.load(f)
                    
                if "base_price" in price_state:
                    self._base_price = float(price_state["base_price"])
                    self._price_range = {
                        'min': float(price_state["min_price"]),
                        'max': float(price_state["max_price"])
                    }
                    self.logger.info(f"保存された価格状態を読み込みました: ¥{self._base_price:,.2f}")
                    return True
                    
            return False
        except Exception as e:
            self.logger.error(f"価格状態読み込みエラー: {e}")
            return False

    def _update_price_range(self, new_price: float):
        """価格帯を更新"""
        try:
            # 基準価格を新しい価格に更新
            self._base_price = float(new_price)
            # 価格帯を±10%で設定
            self._price_range['min'] = self._base_price * 0.9
            self._price_range['max'] = self._base_price * 1.1
            self.logger.info(
                f"Price range updated:\n"
                f"Base: ¥{self._base_price:,.2f}\n"
                f"Min: ¥{self._price_range['min']:,.2f}\n"
                f"Max: ¥{self._price_range['max']:,.2f}"
            )
            
            # 価格帯が更新されたらランダム価格も更新
            self.generate_random_prices()
            
            # 重要な価格更新時に状態を保存（リソース節約のため確率的に）
            if random.random() < 0.2:  # 20%の確率で保存
                self._save_price_state()
            
        except Exception as e:
            self.logger.error(f"Error updating price range: {e}")
            raise