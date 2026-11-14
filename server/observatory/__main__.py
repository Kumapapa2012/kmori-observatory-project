import argparse

import uvicorn

from .app import create_app
from .config import load, resolve

parser = argparse.ArgumentParser(description="天文台サーバー")
parser.add_argument("--config", default="config/observatory.toml")
args = parser.parse_args()
cfg = load(args.config)
server = cfg["server"]
# 位置情報と画面の消灯防止は HTTPS でしか使えない。証明書は tools/make_cert.sh で作る
tls = {"ssl_certfile": str(resolve(server["tls_cert"])), "ssl_keyfile": str(resolve(server["tls_key"]))} \
    if server.get("tls_cert") else {}
uvicorn.run(create_app(cfg), host=server["host"], port=server["port"],
            ws="wsproto", log_level="warning", **tls)
