#!/usr/bin/env bash
# Установка Руинометра на Ubuntu/Debian VPS (запускать от root):
#   curl -fsSL https://raw.githubusercontent.com/Miffk/ruinometr/main/deploy/install.sh | bash
# Свой домен:   ... | DOMAIN=ruin.example.com bash
# Без своего домена берём бесплатный вида 1-2-3-4.sslip.io — Caddy сам выпустит HTTPS-сертификат.
set -euo pipefail

REPO="${REPO:-https://github.com/Miffk/ruinometr.git}"
APP_DIR="${APP_DIR:-/opt/ruinometr}"
APP_USER="ruinometr"
PORT="${PORT:-8000}"
MEMORY_MAX="${MEMORY_MAX:-500M}"   # потолок памяти службы: при превышении перезапустится Руинометр, а не VPN или бот

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Запустите от root (sudo -i)"; exit 1; }

# До любых изменений: хватит ли диска (своп 2 ГБ + Java + код ≈ 2.5 ГБ), чтобы не забить его соседям.
free_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
need_mb=3000
[ "$(swapon --show --noheadings | wc -l)" -gt 0 ] && need_mb=1000
if [ "$free_mb" -lt "$need_mb" ]; then
  echo "На диске свободно ${free_mb} МБ, нужно хотя бы ${need_mb} МБ. Ничего не меняю."
  exit 1
fi

say "Своп"
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ]; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "Создан своп 2 ГБ"
else
  echo "Своп уже есть"
fi
# Своп — только на крайний случай, а не вместо памяти.
sysctl -q vm.swappiness=10 && echo 'vm.swappiness=10' > /etc/sysctl.d/90-ruinometr.conf

say "Пакеты: git, Python, Java 21"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git curl sudo iproute2 python3 python3-venv python3-pip ca-certificates
if ! apt-get install -y -q openjdk-21-jdk-headless; then
  echo "openjdk-21 не нашлась в репозиториях — разбор пойдёт без своего парсера реплеев (без AFK и карты)."
fi

say "Код"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$APP_DIR"
fi
mkdir -p "$APP_DIR/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

say "Python-окружение"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if command -v javac >/dev/null 2>&1; then
  say "Сборка парсера реплеев (пара минут)"
  sudo -u "$APP_USER" env HOME="$APP_DIR" MAVEN_OPTS="-Xmx256m -XX:+UseSerialGC" \
    sh "$APP_DIR/parser/mvnw" -q -f "$APP_DIR/parser/pom.xml" package -DskipTests
fi

say "Служба systemd"
cat > /etc/systemd/system/ruinometr.service <<EOF
[Unit]
Description=Ruinometr — разбор матчей Dota 2
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn ruiner.app:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5
Nice=5
MemoryHigh=420M
MemoryMax=$MEMORY_MAX
Environment=PYTHONUNBUFFERED=1
Environment=RUINER_CACHE_MAX_MB=2000

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now ruinometr
systemctl restart ruinometr

say "HTTPS через Caddy"
if [ -z "${DOMAIN:-}" ]; then
  IP="$(curl -fsS4 https://api.ipify.org || hostname -I | awk '{print $1}')"
  DOMAIN="$(echo "$IP" | tr . -).sslip.io"
fi
busy=""
for p in 80 443; do
  if ss -ltnH "( sport = :$p )" | grep -q . && ! ss -ltnpH "( sport = :$p )" | grep -q caddy; then busy="$busy $p"; fi
done
if [ -n "$busy" ]; then
  echo "Порты$busy уже заняты другим сервисом — Caddy не ставлю."
  echo "Руинометр работает на 127.0.0.1:$PORT; откройте его через свой веб-сервер или поменяйте порт."
  exit 0
fi
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https gnupg
  curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
cat > /etc/caddy/ruinometr.caddy <<EOF
$DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:$PORT
}
EOF
# Стандартный Caddyfile из пакета заменяем на импорт; свой — дополняем импортом.
if grep -q 'root \* /usr/share/caddy' /etc/caddy/Caddyfile 2>/dev/null; then
  echo 'import /etc/caddy/*.caddy' > /etc/caddy/Caddyfile
elif ! grep -q 'import /etc/caddy/\*.caddy' /etc/caddy/Caddyfile; then
  echo 'import /etc/caddy/*.caddy' >> /etc/caddy/Caddyfile
fi
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q active; then ufw allow 80/tcp && ufw allow 443/tcp; fi
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

say "Готово"
echo "Руинометр: https://$DOMAIN"
echo "Логи: journalctl -u ruinometr -f    Обновить: bash $APP_DIR/deploy/update.sh"
