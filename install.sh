#!/usr/bin/env bash
# install.sh — Single-command production installer for fab.engineering
# Usage: git clone https://github.com/fab-agent/agentic-organization.git && cd agentic-organization && bash install.sh
# (run it from a file, in a terminal: the wizard asks questions, so do not pipe it into bash)

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

step() { echo -e "\n${BOLD}${CYAN}▶ $1${NC}"; }
ok()   { echo -e "  ${GREEN}✓ $1${NC}"; }
warn() { echo -e "  ${YELLOW}⚠ $1${NC}"; }
fail() { echo -e "  ${RED}✗ $1${NC}"; exit 1; }

echo ""
echo -e "${BOLD}${CYAN}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║     fab.engineering — Kurulum         ║${NC}"
echo -e "${BOLD}${CYAN}╚═══════════════════════════════════════╝${NC}"
echo ""

# ── 1. Check prerequisites ────────────────────────────────────────────────────
step "Önkoşullar kontrol ediliyor"

command -v docker &>/dev/null || fail "Docker bulunamadı. https://docs.docker.com/engine/install/ adresinden kurun."
ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)"

docker compose version &>/dev/null || fail "Docker Compose v2 bulunamadı. Docker Engine 24+ ile birlikte gelir."
ok "Docker Compose $(docker compose version --short)"

command -v openssl &>/dev/null || command -v python3 &>/dev/null || fail "openssl veya python3 gerekli (JWT_SECRET oluşturmak için)"

# ── 2. Clone or update repo ───────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-/opt/3rdparty-agent-org}"

step "Dizin: ${INSTALL_DIR}"

if [ -d "$INSTALL_DIR/.git" ]; then
    warn "Mevcut kurulum bulundu — güncelleniyor"
    git -C "$INSTALL_DIR" pull --ff-only
    ok "Repo güncellendi"
elif [ "$(pwd)" = "$INSTALL_DIR" ] || [ -f "$(pwd)/docker-compose.prod.yml" ]; then
    INSTALL_DIR="$(pwd)"
    ok "Mevcut dizin kullanılıyor: ${INSTALL_DIR}"
else
    if command -v git &>/dev/null; then
        git clone https://github.com/fab-agent/3rdparty-agent-org.git "$INSTALL_DIR"
        ok "Repo klonlandı → ${INSTALL_DIR}"
    else
        fail "Repo klonlamak için git gerekli ya da INSTALL_DIR içinde çalıştırın."
    fi
fi

cd "$INSTALL_DIR"

# ── 3. Create .env ────────────────────────────────────────────────────────────
step ".env yapılandırması"

if [ -f ".env" ]; then
    warn ".env zaten mevcut — atlanıyor (düzenlemek için: nano .env)"
    source .env 2>/dev/null || true
else
    bash setup-env.sh
    source .env
fi

DOMAIN="${DOMAIN:-localhost}"

# ── 4. Generate nginx.conf from template ─────────────────────────────────────
step "Nginx yapılandırması oluşturuluyor"

if [ "$DOMAIN" = "localhost" ]; then
    warn "Domain 'localhost' — HTTP-only nginx yapılandırması kullanılıyor"
    cat nginx.prod.conf.template \
        | sed 's/listen 443 ssl;//g' \
        | sed '/ssl_/d' \
        | sed '/http2 on;/d' \
        | sed '/Strict-Transport-Security/d' \
        | sed '/X-Content-Type-Options/d' \
        | sed '/X-Frame-Options/d' \
        | sed 's/return 301 https:\/\/$host$request_uri;//g' \
        | sed 's/__DOMAIN__/localhost/g' \
        | sed 's/https:\/\//http:\/\//g' \
        > nginx.conf
    ok "nginx.conf oluşturuldu (HTTP-only, localhost)"
else
    sed "s/__DOMAIN__/${DOMAIN}/g" nginx.prod.conf.template > nginx.conf
    ok "nginx.conf oluşturuldu → domain: ${DOMAIN}"

    # ── 5. Obtain SSL certificate ─────────────────────────────────────────────
    step "Let's Encrypt SSL sertifikası"

    mkdir -p /etc/letsencrypt /var/www/certbot

    if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
        ok "Sertifika zaten mevcut — atlanıyor (yenileme için: certbot renew)"
    else
        REG_EMAIL="${REG_EMAIL:-}"
        if [ -z "$REG_EMAIL" ]; then
            read -rp "  Let's Encrypt için e-posta adresi: " REG_EMAIL
        fi

        echo "  Certbot çalıştırılıyor (port 80 serbest olmalı)..."
        docker run --rm -it \
            -v /etc/letsencrypt:/etc/letsencrypt \
            -v /var/www/certbot:/var/www/certbot \
            -p 80:80 \
            certbot/certbot certonly \
                --standalone \
                --email "$REG_EMAIL" \
                --agree-tos \
                --no-eff-email \
                -d "$DOMAIN" \
            && ok "SSL sertifikası alındı" \
            || fail "Certbot başarısız. Domain DNS kaydının bu sunucuyu gösterdiğinden emin olun."
    fi
fi

# ── 6. Create data directories ────────────────────────────────────────────────
step "Veri dizinleri"
mkdir -p data logs
ok "data/ ve logs/ dizinleri hazır"

# ── 7. Build and start services ───────────────────────────────────────────────
step "Servisler başlatılıyor (bu birkaç dakika sürebilir)"

docker compose -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.prod.yml up -d

ok "Servisler başlatıldı"

# ── 8. Health check ───────────────────────────────────────────────────────────
step "Sistem kontrolü"

sleep 5
BACKEND_OK=false
for i in 1 2 3 4 5; do
    if docker exec 3rdparty-backend curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        BACKEND_OK=true
        break
    fi
    sleep 3
done

if $BACKEND_OK; then
    ok "Backend sağlıklı"
else
    warn "Backend henüz yanıt vermiyor — 'docker compose -f docker-compose.prod.yml logs backend' ile kontrol edin"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║     Kurulum tamamlandı!                   ║${NC}"
echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
if [ "$DOMAIN" = "localhost" ]; then
    echo -e "  Platform: ${CYAN}http://localhost${NC}"
else
    echo -e "  Platform:   ${CYAN}https://${DOMAIN}${NC}"
fi
echo ""
echo "  İlk açılışta kurulum sihirbazı sizi karşılayacak."
echo ""
echo "  Servis durumu için:"
echo -e "    ${YELLOW}docker compose -f docker-compose.prod.yml ps${NC}"
echo ""
