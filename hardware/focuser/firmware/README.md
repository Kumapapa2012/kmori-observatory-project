# フォーカス用 Pico ファームウェア

- `main.py`: Raspberry Pi Pico H (MicroPython) 用。GP15 で FS90R を制御し、USB シリアルで 1 行コマンドを受ける。コマンドはファイル冒頭のコメントを参照。
- `host.py`: 制御ホストから操作する確認用ツール (pyserial が必要)。

Pico への書き込み (このフォルダーで実行):

```sh
mpremote cp main.py :main.py + reset
```

操作の例:

```sh
python3 host.py /dev/ttyACM0 --move 10
```
