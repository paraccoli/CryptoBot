import hashlib
import secrets

def generate_wallet_address() -> str:
    """
    ランダムなウォレットアドレスを生成
    形式: 0x + 40文字のハッシュ
    """
    # ランダムな32バイトの値を生成
    random_bytes = secrets.token_bytes(32)
    
    # SHA-256ハッシュを計算
    hash_object = hashlib.sha256(random_bytes)
    hash_hex = hash_object.hexdigest()
    
    # 最初の40文字を使用してアドレスを生成
    return f"0x{hash_hex[:40]}"