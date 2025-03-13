import tensorflow as tf
import numpy as np
import pandas as pd
from tensorflow.keras import Model
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input, Conv2D, Flatten, Concatenate, BatchNormalization
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import MinMaxScaler, StandardScaler
import yfinance as yf
import joblib
import os
import matplotlib.pyplot as plt
from datetime import datetime

# GPUの設定を強化
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

# モデル作成関数を修正
def create_hybrid_model(lstm_shape, cnn_shape):
    """GPU対応Hybrid LSTMモデル"""
    with tf.device('/GPU:0'):
        # LSTM入力の強化
        lstm_input = Input(shape=lstm_shape)
        x1 = LSTM(256, return_sequences=True, 
                kernel_regularizer=tf.keras.regularizers.l2(0.01))(lstm_input)
        x1 = BatchNormalization()(x1)
        x1 = Dropout(0.4)(x1)
        
        x1 = LSTM(128, return_sequences=True,
                kernel_regularizer=tf.keras.regularizers.l2(0.01))(x1)
        x1 = BatchNormalization()(x1)
        x1 = Dropout(0.4)(x1)
        
        x1 = LSTM(64,
                kernel_regularizer=tf.keras.regularizers.l2(0.01))(x1)
        x1 = BatchNormalization()(x1)
        x1 = Dropout(0.4)(x1)
        
        # CNN入力の強化
        cnn_input = Input(shape=cnn_shape)
        x2 = Conv2D(64, (2, 2), activation='elu', padding='same',
                    kernel_regularizer=tf.keras.regularizers.l2(0.01))(cnn_input)
        x2 = BatchNormalization()(x2)
        x2 = Conv2D(128, (2, 2), activation='elu', padding='same',
                    kernel_regularizer=tf.keras.regularizers.l2(0.01))(x2)
        x2 = BatchNormalization()(x2)
        x2 = Flatten()(x2)
        
        # 結合層の強化
        combined = Concatenate()([x1, x2])
        x = Dense(128, activation='elu',
                kernel_regularizer=tf.keras.regularizers.l2(0.01))(combined)
        x = BatchNormalization()(x)
        x = Dropout(0.3)(x)
        
        x = Dense(64, activation='elu',
                kernel_regularizer=tf.keras.regularizers.l2(0.01))(x)
        x = BatchNormalization()(x)
        output = Dense(1)(x)
        
        model = Model(inputs=[lstm_input, cnn_input], outputs=output)
        
        optimizer = Adam(
            learning_rate=0.001,
            beta_1=0.9,
            beta_2=0.999,
            epsilon=1e-07,
            amsgrad=True
        )
        
        model.compile(
            optimizer=optimizer,
            loss='huber_loss',
            metrics=['mae', 'mse']
        )
        
        return model

# コールバックの強化
def create_callbacks():
    """学習用のコールバックを作成"""
    return [
        tf.keras.callbacks.EarlyStopping(
            monitor='val_loss',
            patience=20,
            restore_best_weights=True,
            min_delta=1e-4
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.2,
            patience=8,
            min_lr=1e-6,
            verbose=1
        ),
        tf.keras.callbacks.ModelCheckpoint(
            'src/models/hybrid_lstm_model_best.h5',
            save_best_only=True,
            monitor='val_loss'
        ),
        tf.keras.callbacks.TensorBoard(
            log_dir='src/logs/hybrid_lstm_training',
            histogram_freq=1
        ),
        tf.keras.callbacks.TerminateOnNaN()
    ]

def prepare_data(df, sequence_length=20):
    """データの前処理（修正版）"""
    # 標準化を追加
    scaler = StandardScaler()
    df[['price', 'volume']] = scaler.fit_transform(df[['price', 'volume']])
    
    features = ['price', 'MA5', 'MA10', 'RSI', 'volume_change', 'volatility']
    lstm_data = []
    cnn_data = []
    targets = []
    
    for i in range(len(df) - sequence_length):
        # LSTM特徴量
        lstm_seq = df[features].iloc[i:i+sequence_length].values
        
        # CNN特徴量（5x5マトリックス）
        if i >= 4:
            price_matrix = []
            volume_matrix = []
            for k in range(5):
                price_row = df['price'].iloc[i-k:i-k+5].values
                volume_row = df['volume'].iloc[i-k:i-k+5].values
                price_matrix.append(price_row)
                volume_matrix.append(volume_row)
            
            cnn_feature = np.stack([price_matrix, volume_matrix], axis=-1)
            cnn_data.append(cnn_feature)
            lstm_data.append(lstm_seq)
            targets.append(df['price'].iloc[i+sequence_length])
    
    return np.array(lstm_data), np.array(cnn_data), np.array(targets), scaler

def plot_training_history(history):
    """学習履歴のプロット"""
    plt.figure(figsize=(12, 4))
    plt.style.use('dark_background')
    
    plt.subplot(1, 2, 1)
    plt.plot(history.history['loss'], label='Training Loss', color='#00ff00')
    plt.plot(history.history['val_loss'], label='Validation Loss', color='#ff0000')
    plt.title('Model Loss (Hybrid LSTM-CNN)')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.legend()
    plt.grid(True, alpha=0.2)
    
    plt.subplot(1, 2, 2)
    plt.plot(history.history['mae'], label='Training MAE', color='#00ff00')
    plt.plot(history.history['val_mae'], label='Validation MAE', color='#ff0000')
    plt.title('Model MAE (Hybrid LSTM-CNN)')
    plt.xlabel('Epoch')
    plt.ylabel('MAE')
    plt.legend()
    plt.grid(True, alpha=0.2)
    
    plt.tight_layout()
    plt.savefig('src/models/hybrid_training_history.png', facecolor='#2f3136')
    plt.close()

# main関数内のモデル学習部分を修正
def main():
    os.makedirs('src/models', exist_ok=True)
    
    try:
        # データ取得と前処理
        tickers = ['BTC-USD', 'ETH-USD']
        all_data = []
        
        for ticker in tickers:
            data = yf.download(
                ticker,
                start='2020-01-01',
                end=datetime.now().strftime('%Y-%m-%d'),
                interval='1d'
            )
            df = pd.DataFrame()
            df['price'] = data['Close']
            df['volume'] = data['Volume']
            df['high'] = data['High']
            df['low'] = data['Low']
            
            # テクニカル指標の計算
            df['MA5'] = df['price'].rolling(window=5).mean()
            df['MA10'] = df['price'].rolling(window=10).mean()
            
            delta = df['price'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            df['volume_change'] = df['volume'].pct_change()
            df['volatility'] = (df['high'] - df['low']) / df['price']
            
            all_data.append(df)
        
        combined_df = pd.concat(all_data)
        combined_df = combined_df.sort_index()
        combined_df = combined_df.fillna(method='ffill').fillna(0)
        
        # データのスケーリング
        features = ['price', 'MA5', 'MA10', 'RSI', 'volume_change', 'volatility']
        scaler = MinMaxScaler()
        combined_df[features] = scaler.fit_transform(combined_df[features])
        
        # データの準備（修正）
        lstm_data, cnn_data, targets, scaler = prepare_data(combined_df)
        
        # データの分割
        train_size = int(len(lstm_data) * 0.7)
        val_size = int(len(lstm_data) * 0.15)
        
        X_lstm_train = lstm_data[:train_size]
        X_cnn_train = cnn_data[:train_size]
        y_train = targets[:train_size]
        
        X_lstm_val = lstm_data[train_size:train_size+val_size]
        X_cnn_val = cnn_data[train_size:train_size+val_size]
        y_val = targets[train_size:train_size+val_size]
        
        X_lstm_test = lstm_data[train_size+val_size:]
        X_cnn_test = cnn_data[train_size+val_size:]
        y_test = targets[train_size+val_size:]
        
        # モデルの構築と学習
        with tf.device('/GPU:0'):
            model = create_hybrid_model(
                lstm_shape=(20, len(features)),
                cnn_shape=(5, 5, 2)
            )
            print("GPUを使用して学習を開始します...")
            
            callbacks = create_callbacks()
            history = model.fit(
                [X_lstm_train, X_cnn_train],
                y_train,
                validation_data=([X_lstm_val, X_cnn_val], y_val),
                epochs=300,
                batch_size=64,  # GPUメモリに合わせて調整
                callbacks=callbacks,
                verbose=1,
                shuffle=True
            )
        
        # モデルの評価部分を修正
        test_metrics = model.evaluate(
            [X_lstm_test, X_cnn_test],
            y_test,
            verbose=0
        )

        print('\nテスト結果:')
        print(f'Loss (Huber): {test_metrics[0]:.4f}')
        print(f'MAE: {test_metrics[1]:.4f}')
        print(f'MSE: {test_metrics[2]:.4f}')
        
        # 学習履歴のプロット
        plot_training_history(history)
        
        # モデルとスケーラーの保存
        model.save('src/models/hybrid_lstm_model.h5')
        joblib.dump(scaler, 'src/models/hybrid_price_scaler.pkl')
        
        print("\nモデルとスケーラーを保存しました:")
        print("- src/models/hybrid_lstm_model.h5")
        print("- src/models/hybrid_price_scaler.pkl")
        print("- src/models/hybrid_training_history.png")
        
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")
        raise

if __name__ == "__main__":
    main()