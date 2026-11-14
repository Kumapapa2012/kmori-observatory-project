"""設定ファイルの読み込み。"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve(path):
    """プロジェクトのルートからのパスを絶対パスにする。"""
    path = Path(path)
    return path if path.is_absolute() else ROOT / path
