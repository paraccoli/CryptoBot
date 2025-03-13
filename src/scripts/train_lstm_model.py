import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
from tensorflow.keras.optimizers import Adam
import joblib
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import tensorflow as tf

# TensorFlowのログレベルを設定
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '1'

# GPU設定の初期化
print("=== GPU設定の初期化 ===")
print(f"TensorFlow version: {tf.__version__}")

gpus = tf.config.list_physical_devices('GPU')
if gpus:
    try:
        # すべてのGPUでメモリ成長を有効化
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
            
        # 論理的なGPUの設定
        tf.config.experimental.set_visible_devices(gpus[0], 'GPU')
        logical_gpus = tf.config.experimental.list_logical_devices('GPU')
        
        print(f"利用可能なGPU: {len(gpus)}")
        print(f"利用可能な論理GPU: {len(logical_gpus)}")
        print("GPUメモリ動的確保: 有効")
        
    except RuntimeError as e:
        print(f"GPU設定エラー: {e}")
else:
    print("警告: 利用可能なGPUが見つかりません")

def create_sequences(data, seq_length):
    """時系列データをシーケンスに変換"""
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i:(i + seq_length)])
        y.append(data[i + seq_length, 0])
    return np.array(X), np.array(y)

# create_lstm_modelの修正

def create_lstm_model(input_shape):
    """改良版LSTMモデルの構築"""
    with tf.device('/GPU:0'):
        model = Sequential([
            # 入力層
            LSTM(512, input_shape=input_shape, return_sequences=True,
                kernel_regularizer=tf.keras.regularizers.l2(0.01)),
            BatchNormalization(),
            Dropout(0.4),
            
            # 中間層1
            LSTM(256, return_sequences=True,
                kernel_regularizer=tf.keras.regularizers.l2(0.01)),
            BatchNormalization(),
            Dropout(0.4),
            
            # 中間層2
            LSTM(128, return_sequences=False,
                kernel_regularizer=tf.keras.regularizers.l2(0.01)),
            BatchNormalization(),
            Dropout(0.4),
            
            # 全結合層
            Dense(64, activation='relu',
                kernel_regularizer=tf.keras.regularizers.l2(0.01)),
            BatchNormalization(),
            Dropout(0.3),
            
            Dense(32, activation='relu',
                kernel_regularizer=tf.keras.regularizers.l2(0.01)),
            BatchNormalization(),
            
            # 出力層
            Dense(1)
        ])
        
        optimizer = Adam(
            learning_rate=0.001,
            beta_1=0.9,
            beta_2=0.999,
            epsilon=1e-07,
            amsgrad=True  # 追加
        )
        
        model.compile(
            optimizer=optimizer,
            loss='huber_loss',
            metrics=['mae', 'mse']
        )
        
        return model

def plot_training_history(history):
    """学習履歴のプロット"""
    plt.figure(figsize=(12, 4))
    plt.style.use('dark_background')
    
    plt.subplot(1, 2, 1)
    plt.plot(history.history['loss'], label='Training Loss', color='#00ff00')
    plt.plot(history.history['val_loss'], label='Validation Loss', color='#ff0000')
    plt.title('Model Loss')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.legend()
    plt.grid(True, alpha=0.2)
    
    plt.subplot(1, 2, 2)
    plt.plot(history.history['mae'], label='Training MAE', color='#00ff00')
    plt.plot(history.history['val_mae'], label='Validation MAE', color='#ff0000')
    plt.title('Model MAE')
    plt.xlabel('Epoch')
    plt.ylabel('MAE')
    plt.legend()
    plt.grid(True, alpha=0.2)
    
    plt.tight_layout()
    plt.savefig('src/models/training_history.png', facecolor='#2f3136')
    plt.close()

def create_callbacks():
    """学習用のコールバックを作成"""
    return [
        tf.keras.callbacks.EarlyStopping(
            monitor='val_loss',
            patience=15,
            restore_best_weights=True,
            min_delta=1e-4
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.2,
            patience=5,
            min_lr=1e-6
        ),
        tf.keras.callbacks.ModelCheckpoint(
            'src/models/lstm_price_model_best.h5',
            save_best_only=True,
            monitor='val_loss'
        ),
        tf.keras.callbacks.TensorBoard(
            log_dir='src/logs/lstm_training',
            histogram_freq=1
        )
    ]

# データ型の変換を行う関数を追加
def prepare_data(X, y):
    """データを適切な型に変換"""
    X = tf.cast(X, tf.float32)
    y = tf.cast(y, tf.float32)
    return X, y

# モデルの評価部分を修正
def main():
    os.makedirs('src/models', exist_ok=True)
    
    try:
        # データ取得期間の拡大
        tickers = ['BTC-USD', 'ETH-USD', 'USDT-USD', 'BNB-USD']
        start_date = '2019-01-01'  # より長期のデータ
        
        all_data = []
        for ticker in tickers:
            data = yf.download(
                ticker,
                start=start_date,
                end=datetime.now().strftime('%Y-%m-%d'),
                interval='1d'
            )
            
            df = pd.DataFrame()
            df['price'] = data['Close']
            df['volume'] = data['Volume']
            df['high'] = data['High']
            df['low'] = data['Low']
            
            # テクニカル指標の追加
            df['MA5'] = df['price'].rolling(window=5).mean()
            df['MA10'] = df['price'].rolling(window=10).mean()
            df['MA20'] = df['price'].rolling(window=20).mean()
            df['MA50'] = df['price'].rolling(window=50).mean()  # 追加

            # ボラティリティ指標
            df['volatility'] = df['price'].rolling(window=20).std() / df['price']
            df['volume_change'] = df['volume'].pct_change()

            # モメンタム指標
            df['ROC'] = df['price'].pct_change(periods=10) * 100  # 追加
            df['MOM'] = df['price'].diff(10)  # 追加

            # 価格変化率
            df['price_change'] = df['price'].pct_change()
            df['high_low_ratio'] = (df['high'] - df['low']) / df['low']
            
            # RSI計算の改善
            delta = df['price'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            rs = avg_gain / avg_loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # ボリンジャーバンド
            std_dev = df['price'].rolling(window=20).std()
            df['BB_upper'] = df['MA20'] + (std_dev * 2)
            df['BB_lower'] = df['MA20'] - (std_dev * 2)
            
            # MACDの追加
            exp1 = df['price'].ewm(span=12, adjust=False).mean()
            exp2 = df['price'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            all_data.append(df)

        # データの結合
        combined_df = pd.concat(all_data)
        combined_df = combined_df.sort_index()
        
        print(f"取得したデータ数: {len(combined_df)}")
        
        # 欠損値の処理
        combined_df = combined_df.fillna(method='ffill')
        combined_df = combined_df.fillna(0)
        
        print("データ前処理完了")
        print(f"特徴量の形状: {combined_df.shape}")
        
        # スケーリング
        features = [
            'price', 'volume', 
            'MA5', 'MA10', 'MA20', 'MA50',
            'volatility', 'volume_change',
            'ROC', 'MOM', 
            'RSI', 'MACD',
            'BB_upper', 'BB_lower',
            'high_low_ratio', 'price_change'
        ]

        scaler = MinMaxScaler()
        scaled_data = scaler.fit_transform(combined_df[features])
        
        # シーケンスデータの作成
        sequence_length = 20  # シーケンス長を増やす
        X, y = create_sequences(scaled_data, sequence_length)
        
        print(f"学習データの形状: X={X.shape}, y={y.shape}")
        
        # データの分割と前処理
        train_size = int(len(X) * 0.7)
        val_size = int(len(X) * 0.15)

        # データ分割
        X_train, y_train = X[:train_size], y[:train_size]
        X_val, y_val = X[train_size:train_size+val_size], y[train_size:train_size+val_size]
        X_test, y_test = X[train_size+val_size:], y[train_size+val_size:]

        # データ型の変換
        X_train, y_train = prepare_data(X_train, y_train)
        X_val, y_val = prepare_data(X_val, y_val)
        X_test, y_test = prepare_data(X_test, y_test)

        # モデルの構築と学習
        with tf.device('/GPU:0'):
            model = create_lstm_model((sequence_length, len(features)))
            print("GPUを使用して学習を開始します...")
            
            # 学習部分の修正
            callbacks = create_callbacks()
            history = model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val),
                epochs=300,  # エポック数増加
                batch_size=128,  # GPUメモリに合わせて調整
                callbacks=callbacks,
                verbose=1,
                shuffle=True  # データのシャッフルを有効化
            )
        
        # モデルの評価を修正
        test_metrics = model.evaluate(X_test, y_test, verbose=0)
        metrics_names = model.metrics_names
        
        print("\nテスト結果:")
        for name, value in zip(metrics_names, test_metrics):
            print(f'{name}: {value:.4f}')
        
        # 学習履歴のプロット
        plot_training_history(history)
        
        # モデルとスケーラーの保存
        model.save('src/models/lstm_price_model.h5')
        joblib.dump(scaler, 'src/models/price_scaler.pkl')
        
        print("\nモデルとスケーラーを保存しました:")
        print("- src/models/lstm_price_model.h5")
        print("- src/models/price_scaler.pkl")
        print("- src/models/training_history.png")
        
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")
        raise

if __name__ == "__main__":
    main()