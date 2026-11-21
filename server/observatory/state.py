"""再起動や切断をまたいで残す状態。ホストが正本で、SPA は接続のたびに受け取る。"""
import json
import os
import threading
from pathlib import Path

# finder はファインダーの映像の中で主鏡の中心が写る位置（幅と高さに対する割合）
# site は画面から保存した観測地で、None なら設定ファイルの値を使う
# sky_mask は見えている空の範囲（plate.py、方位 10° ごとの可否と高度の下限）で、None なら全方位
DEFAULT = {"site": None, "alignment": None, "recording": {"kind": "none"}, "finder": {"x": 0.5, "y": 0.5},
           "sky_mask": None}


class StateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data = json.loads(json.dumps(DEFAULT))
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except ValueError:
            # 壊れたファイルで起動できなくなるより、既定値で動いて上書きする
            print(f"ignored broken state file: {self.path}", flush=True)

    def get(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def update(self, **values):
        with self.lock:
            self.data.update(values)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 書き込み中に電源が落ちても、前の内容か新しい内容のどちらかが残るようにする
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
