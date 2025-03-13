import tensorflow as tf
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import joblib
import os
from ..database.database import SessionLocal
from ..database.models import PriceHistory
from sqlalchemy import desc
import logging
from sklearn.linear_model import LinearRegression
from prophet import Prophet
from xgboost import XGBRegressor

# TensorFlowの警告を完全に抑制
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)

# GPUを無効化
tf.config.set_visible_devices([], 'GPU')

class PricePredictor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # モデルパスの設定
        self.lstm_model_path = 'src/models/lstm_price_model.h5'
        self.hybrid_model_path = 'src/models/hybrid_lstm_model.h5'
        self.lstm_scaler_path = 'src/models/price_scaler.pkl'
        self.hybrid_scaler_path = 'src/models/hybrid_price_scaler.pkl'
        
        try:
            custom_objects = {'Adam': tf.keras.optimizers.legacy.Adam}
            with tf.device('/CPU:0'):
                # LSTMモデル
                self.lstm_model = tf.keras.models.load_model(
                    self.lstm_model_path,
                    custom_objects=custom_objects
                )
                # Hybridモデル
                self.hybrid_model = tf.keras.models.load_model(
                    self.hybrid_model_path,
                    custom_objects=custom_objects
                )
            self.lstm_scaler = joblib.load(self.lstm_scaler_path)
            self.hybrid_scaler = joblib.load(self.hybrid_scaler_path)
            self.logger.info("全モデルとスケーラーを正常に読み込みました")
        except Exception as e:
            self.logger.error(f"モデルの読み込みに失敗: {str(e)}")
            self.lstm_model = None
            self.hybrid_model = None
            self.lstm_scaler = None
            self.hybrid_scaler = None

    async def predict_price(self, minutes: int = 10, model_type: str = "hybrid") -> dict:
        """
        価格予測を実行
        Args:
            minutes (int): 予測する時間（分単位、1-60分）
            model_type (str): 使用するモデルの種類（"hybrid", "lstm", "prophet", "xgboost", "linear", "ensemble"）
        """
        # 予測時間の制限
        minutes = max(1, min(60, minutes))  # 1-60分の範囲に制限
        
        if model_type == "lstm" and (not self.lstm_model or not self.lstm_scaler):
            return {
                'success': False,
                'error': 'LSTMモデルが読み込まれていません'
            }

        db = SessionLocal()
        try:
            # 必要なデータ数を20に減らす
            MIN_DATA_POINTS = 20

            # 直近のデータを取得
            raw_history = db.query(PriceHistory)\
                .order_by(desc(PriceHistory.timestamp))\
                .limit(50)\
                .all()
            
            if not raw_history:
                return {
                    'success': False,
                    'error': 'データが見つかりません'
                }
            
            # データの前処理と変換
            history_data = []
            latest_valid_price = None

            for record in raw_history:
                try:
                    # 最新の有効な価格を保持
                    if record.price is not None and record.price > 0:
                        latest_valid_price = float(record.price)

                    # 欠損値を補完
                    price = float(record.price) if record.price is not None else latest_valid_price
                    volume = float(record.volume) if record.volume is not None else 0
                    high = float(record.high) if record.high is not None else price
                    low = float(record.low) if record.low is not None else price

                    if price and price > 0:  # 価格が有効な場合のみデータを追加
                        history_data.append({
                            'timestamp': record.timestamp,
                            'price': price,
                            'volume': max(0, volume),
                            'high': max(price, high),
                            'low': min(price, low) if low > 0 else price
                        })
                except (TypeError, ValueError) as e:
                    self.logger.warning(f"データ変換スキップ: {str(e)}")
                    continue

            history_data.reverse()
            
            if len(history_data) < MIN_DATA_POINTS:
                return {
                    'success': False,
                    'error': f'有効なデータが不足しています（必要: {MIN_DATA_POINTS}, 現在: {len(history_data)}）'
                }

            # 必要な数のデータのみを使用
            history_data = history_data[-MIN_DATA_POINTS:]

            # データ補完（移動平均で）
            df = pd.DataFrame(history_data)
            df['price'] = df['price'].fillna(method='ffill').fillna(method='bfill')
            df['volume'] = df['volume'].fillna(0)
            df['high'] = df['high'].fillna(df['price'])
            df['low'] = df['low'].fillna(df['price'])

            # データをリストに戻す
            history_data = df.to_dict('records')

            # 予測時の時間単位を分に変更
            if model_type == "hybrid":
                return await self._predict_hybrid(history_data, minutes)
            elif model_type == "lstm":
                return await self._predict_lstm(history_data, minutes)
            elif model_type == "prophet":
                return await self._predict_prophet(history_data, minutes)
            elif model_type == "xgboost":
                return await self._predict_xgboost(history_data, minutes)
            elif model_type == "ensemble":
                return await self._predict_ensemble(history_data, minutes)
            else:
                return await self._predict_linear(history_data, minutes)

        except Exception as e:
            self.logger.error(f"予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }
        finally:
            db.close()

    async def _predict_lstm(self, history: list, minutes: int) -> dict:
        """LSTMモデルによる予測"""
        if not self.lstm_model or not self.lstm_scaler:
            return {
                'success': False,
                'error': 'LSTMモデルが読み込まれていません'
            }
            
        try:
            # 特徴量名を学習時と完全に同じ順序で定義
            feature_names = [
                'price', 'volume',
                'MA5', 'MA10', 'MA20', 'MA50',
                'volatility', 'volume_change',
                'ROC', 'MOM',
                'RSI', 'MACD',
                'BB_upper', 'BB_lower',
                'high_low_ratio', 'price_change'
            ]
            
            # データフレームの作成
            df = pd.DataFrame(history)
            
            # 必要な特徴量の計算
            # 移動平均
            df['MA5'] = df['price'].rolling(window=5).mean()
            df['MA10'] = df['price'].rolling(window=10).mean()
            df['MA20'] = df['price'].rolling(window=20).mean()
            df['MA50'] = df['price'].rolling(window=50).mean()

            # ボラティリティと出来高変化
            df['volatility'] = df['price'].rolling(window=20).std() / df['price']
            df['volume_change'] = df['volume'].pct_change()

            # モメンタム指標
            df['ROC'] = df['price'].pct_change(periods=10) * 100
            df['MOM'] = df['price'].diff(10)

            # 価格変化率
            df['price_change'] = df['price'].pct_change()
            df['high_low_ratio'] = (df['high'] - df['low']) / df['low']

            # RSI
            delta = df['price'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            rs = avg_gain / avg_loss
            df['RSI'] = 100 - (100 / (1 + rs))

            # MACD
            exp1 = df['price'].ewm(span=12, adjust=False).mean()
            exp2 = df['price'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2

            # ボリンジャーバンド
            std_dev = df['price'].rolling(window=20).std()
            df['BB_upper'] = df['MA20'] + (std_dev * 2)
            df['BB_lower'] = df['MA20'] - (std_dev * 2)

            # 欠損値の処理
            df = df.fillna(method='ffill').fillna(0)

            # 特徴量の抽出と異常値の除去
            features_df = df[feature_names]
            for col in feature_names:
                mean = features_df[col].mean()
                std = features_df[col].std()
                features_df[col] = features_df[col].clip(mean - 3*std, mean + 3*std)

            # スケーリングとモデル予測
            scaled_features = self.lstm_scaler.transform(features_df)
            X = np.expand_dims(scaled_features[-20:], axis=0)
            
            with tf.device('/CPU:0'):
                scaled_prediction = self.lstm_model.predict(X, verbose=0)

            # 予測値の逆変換
            inverse_data = pd.DataFrame(np.zeros((1, len(feature_names))), columns=feature_names)
            inverse_data.iloc[0, 0] = scaled_prediction[0, 0]
            prediction = float(self.lstm_scaler.inverse_transform(inverse_data)[0, 0])

            # 予測値の範囲制限を更新
            latest_price = float(df['price'].iloc[-1])
            prediction = self._limit_prediction(prediction, latest_price)

            # 信頼度とグラフの生成
            confidence = self._calculate_confidence(history[-20:], prediction)
            graph_path = self._generate_prediction_graph(history[-20:], prediction, minutes)

            return {
                'success': True,
                'predicted_price': prediction,
                'confidence': confidence,
                'graph': graph_path
            }

        except Exception as e:
            self.logger.error(f"LSTM予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }

    async def _predict_linear(self, history: list, hours: int) -> dict:
        """線形回帰モデルによる予測"""
        try:
            # 特徴量として価格と時間を使用
            X = np.array(range(len(history))).reshape(-1, 1)
            y = np.array([h['price'] for h in history])

            # 線形回帰モデルの作成と学習
            model = LinearRegression()
            model.fit(X, y)

            # 予測
            future_point = np.array([[len(history) + hours]])
            prediction = float(model.predict(future_point)[0])

            # 信頼度の計算（R²スコアを使用）
            confidence = max(0, min(1, model.score(X, y)))

            # グラフの生成
            graph_path = self._generate_prediction_graph(history, prediction, hours)

            return {
                'success': True,
                'predicted_price': prediction,
                'confidence': confidence,
                'graph': graph_path
            }

        except Exception as e:
            self.logger.error(f"線形回帰予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }

    async def _predict_prophet(self, history: list, minutes: int) -> dict:
        """Prophetモデルによる予測（分単位）"""
        try:
            # データフレームの準備
            df = pd.DataFrame({
                'ds': [h['timestamp'] for h in history],
                'y': [h['price'] for h in history]
            })
            
            # モデルの設定と学習
            model = Prophet(
                changepoint_prior_scale=0.05,
                seasonality_prior_scale=10,
                daily_seasonality=True
            )
            model.fit(df)
            
            # 予測期間の設定（分単位）
            future = model.make_future_dataframe(periods=minutes, freq='T')  # 'T'は分を表す
            forecast = model.predict(future)
            
            # 予測値の取得
            prediction = float(forecast.iloc[-1]['yhat'])
            
            # 信頼度の計算（予測区間から）
            confidence = 1 - (forecast.iloc[-1]['yhat_upper'] - forecast.iloc[-1]['yhat_lower']) / (2 * prediction)
            
            return {
                'success': True,
                'predicted_price': prediction,
                'confidence': confidence,
                'graph': self._generate_prediction_graph(history, prediction, minutes)
            }
        
        except Exception as e:
            self.logger.error(f"Prophet予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }

    async def _predict_xgboost(self, history: list, hours: int) -> dict:
        """XGBoostモデルによる予測"""
        try:
            # 特徴量エンジニアリング
            features = []
            targets = []
            for i in range(len(history) - hours):
                # 価格、出来高、高値、安値の時系列特徴量
                feature = [
                    history[i + j]['price'] for j in range(hours)
                ] + [
                    history[i + j]['volume'] for j in range(hours)
                ] + [
                    history[i + j]['high'] for j in range(hours)
                ] + [
                    history[i + j]['low'] for j in range(hours)
                ]
                target = history[i + hours]['price']
                features.append(feature)
                targets.append(target)
            
            # モデルの学習
            model = XGBRegressor(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=3
            )
            model.fit(features, targets)
            
            # 予測
            latest_feature = [
                history[-hours + j]['price'] for j in range(hours)
            ] + [
                history[-hours + j]['volume'] for j in range(hours)
            ] + [
                history[-hours + j]['high'] for j in range(hours)
            ] + [
                history[-hours + j]['low'] for j in range(hours)
            ]
            
            prediction = float(model.predict([latest_feature])[0])
            
            # 信頼度の計算（モデルのスコアを使用）
            confidence = max(0, min(1, model.score(features, targets)))
            
            return {
                'success': True,
                'predicted_price': prediction,
                'confidence': confidence,
                'graph': self._generate_prediction_graph(history, prediction, hours)
            }
            
        except Exception as e:
            self.logger.error(f"XGBoost予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }

    async def _predict_ensemble(self, history: list, hours: int) -> dict:
        """複数モデルを組み合わせた予測"""
        try:
            # 各モデルの予測を取得
            lstm_result = await self._predict_lstm(history, hours)
            linear_result = await self._predict_linear(history, hours)
            prophet_result = await self._predict_prophet(history, hours)
            xgboost_result = await self._predict_xgboost(history, hours)
            
            # 成功した予測のみを使用
            predictions = []
            confidences = []
            
            for result in [lstm_result, linear_result, prophet_result, xgboost_result]:
                if result['success']:
                    predictions.append(result['predicted_price'])
                    confidences.append(result['confidence'])
            
            if not predictions:
                return {
                    'success': False,
                    'error': '有効な予測がありません'
                }
            
            # 信頼度による重み付け平均
            weighted_sum = sum(p * c for p, c in zip(predictions, confidences))
            total_confidence = sum(confidences)
            
            prediction = weighted_sum / total_confidence if total_confidence > 0 else sum(predictions) / len(predictions)
            confidence = sum(confidences) / len(confidences)
            
            return {
                'success': True,
                'predicted_price': prediction,
                'confidence': confidence,
                'graph': self._generate_prediction_graph(history, prediction, hours)
            }
            
        except Exception as e:
            self.logger.error(f"アンサンブル予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }

    async def _predict_hybrid(self, history: list, minutes: int) -> dict:
        """Hybrid LSTM-CNNモデルによる予測"""
        try:
            if not self.hybrid_model or not self.hybrid_scaler:
                return {
                    'success': False,
                    'error': 'Hybridモデルが読み込まれていません'
                }

            # データの前処理
            df = pd.DataFrame(history)
            df['MA5'] = df['price'].rolling(window=5).mean()
            df['MA10'] = df['price'].rolling(window=10).mean()
            
            # RSI計算
            delta = df['price'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            rs = avg_gain / avg_loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # ボリューム変化率と変動性
            df['volume_change'] = df['volume'].pct_change()
            df['volatility'] = (df['high'] - df['low']) / df['price']
            
            # 欠損値の処理
            df = df.fillna(method='ffill').fillna(0)

            # 特徴量のスケーリング
            features = ['price', 'volume']  # StandardScalerで使用する特徴量
            scaled_features = self.hybrid_scaler.transform(df[features])
            
            # スケーリングされた値を元のデータフレームに戻す
            df['price_scaled'] = scaled_features[:, 0]
            df['volume_scaled'] = scaled_features[:, 1]

            # CNN特徴量マトリックスの作成（スケーリング済みデータを使用）
            price_matrix = []
            volume_matrix = []
            for i in range(5):
                if len(df) >= 5:
                    price_row = df['price_scaled'].iloc[-5:].values
                    volume_row = df['volume_scaled'].iloc[-5:].values
                    price_matrix.append(price_row)
                    volume_matrix.append(volume_row)

            # LSTM特徴量の準備
            lstm_features = ['price_scaled', 'MA5', 'MA10', 'RSI', 'volume_change', 'volatility']
            lstm_data = df[lstm_features].values
            lstm_input = np.expand_dims(lstm_data[-20:], axis=0)

            # CNN特徴量の準備
            cnn_data = np.stack([price_matrix, volume_matrix], axis=-1)
            cnn_input = np.expand_dims(cnn_data, axis=0)

            # 予測
            with tf.device('/CPU:0'):
                scaled_prediction = self.hybrid_model.predict(
                    [lstm_input, cnn_input],
                    verbose=0
                )[0][0]

            # 予測値のスケール戻し
            prediction_reshaped = np.array([[scaled_prediction, 0]])  # volume用のダミー値を追加
            unscaled_prediction = self.hybrid_scaler.inverse_transform(prediction_reshaped)[0, 0]

            # 予測値の範囲制限
            latest_price = float(df['price'].iloc[-1])
            unscaled_prediction = self._limit_prediction(unscaled_prediction, latest_price)

            # 信頼度とグラフの生成
            confidence = self._calculate_confidence(history[-20:], unscaled_prediction)
            graph_path = self._generate_prediction_graph(history[-20:], unscaled_prediction, minutes)

            return {
                'success': True,
                'predicted_price': unscaled_prediction,
                'confidence': confidence,
                'graph': graph_path
            }

        except Exception as e:
            self.logger.error(f"Hybrid LSTM予測エラー: {str(e)}")
            return {
                'success': False,
                'error': f'予測に失敗しました: {str(e)}'
            }

    def _calculate_confidence(self, history: list, prediction: float) -> float:
        """予測の信頼度を計算"""
        try:
            # 直近の価格変動の標準偏差を計算
            prices = [h['price'] for h in history]
            std_dev = np.std(prices)
            
            # 予測値と最新値の差
            latest_price = history[-1]['price']
            price_diff = abs(prediction - latest_price)
            
            # 信頼度の計算（差が小さいほど信頼度が高い）
            confidence = max(0, min(1, 1 - (price_diff / (3 * std_dev))))
            
            return confidence
            
        except Exception as e:
            self.logger.error(f"信頼度計算エラー: {str(e)}")
            return 0.5

    def _generate_prediction_graph(self, history: list, prediction: float, minutes: int) -> str:
        """予測グラフの生成（分単位）"""
        try:
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(10, 6))
            fig.patch.set_facecolor('#2f3136')
            ax.set_facecolor('#2f3136')

            # 履歴データのプロット
            dates = [h['timestamp'] for h in history]
            prices = [h['price'] for h in history]
            ax.plot(dates, prices, 'b-', label='Historical Price')

            # 予測値のプロット（分単位）
            last_date = dates[-1]
            prediction_date = last_date + pd.Timedelta(minutes=minutes)
            ax.plot([last_date, prediction_date], [prices[-1], prediction], 'r--', label='Prediction')
            ax.scatter(prediction_date, prediction, color='red', s=100)

            # グラフの設定
            ax.set_title(f'PARC Price Prediction ({minutes}分後)', color='white', pad=20)
            ax.set_xlabel('Time', color='white')
            ax.set_ylabel('Price (JPY)', color='white')
            ax.tick_params(colors='white')
            ax.grid(True, alpha=0.2)
            ax.legend()

            # グラフの保存
            save_path = 'temp/prediction_graph.png'
            os.makedirs('temp', exist_ok=True)
            plt.savefig(save_path, dpi=100, bbox_inches='tight', 
                       facecolor='#2f3136', edgecolor='none')
            plt.close()

            return save_path

        except Exception as e:
            self.logger.error(f"グラフ生成エラー: {str(e)}")
            return None

    # 予測値の範囲制限を修正
    def _limit_prediction(self, prediction: float, latest_price: float) -> float:
        """予測値の範囲を制限"""
        if np.isnan(prediction) or np.isinf(prediction):
            return latest_price
        
        # 変動幅を±5%に制限
        max_change = 0.05
        lower_limit = latest_price * (1 - max_change)
        upper_limit = latest_price * (1 + max_change)
    
        return min(max(prediction, lower_limit), upper_limit)
