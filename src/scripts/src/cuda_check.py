import tensorflow as tf

# GPUの使用確認
print("TensorFlow version:", tf.__version__)
print("GPU Available:", tf.test.is_gpu_available())

# 簡単なGPU演算テスト
with tf.device('/GPU:0'):
    a = tf.random.normal([1000, 1000])
    b = tf.random.normal([1000, 1000])
    c = tf.matmul(a, b)

print("GPU計算テスト完了")
print("計算結果の形状:", c.shape)