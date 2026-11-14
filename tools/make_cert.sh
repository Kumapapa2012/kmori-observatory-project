#!/bin/sh
# 自己署名証明書を var/tls に作る。ホストの IP アドレスが変わったら作り直す。
# 追加の名前やアドレスは引数で渡す（例: tools/make_cert.sh IP:10.42.0.1）
set -eu
cd "$(dirname "$0")/.."
mkdir -p var/tls
chmod 700 var/tls

host=$(hostname)
san="DNS:$host,DNS:$host.local,DNS:localhost,IP:127.0.0.1"
for ip in $(hostname -I); do
  case "$ip" in *:*) ;; *) san="$san,IP:$ip" ;; esac
done
for extra in "$@"; do san="$san,$extra"; done

# iOS は有効期間が 825 日を超える証明書を受け付けない
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -days 825 -subj "/CN=$host observatory" \
  -addext "subjectAltName=$san" \
  -addext "extendedKeyUsage=serverAuth" \
  -keyout var/tls/key.pem -out var/tls/cert.pem 2>/dev/null
chmod 600 var/tls/key.pem
echo "作成しました: var/tls/cert.pem ($san)"
