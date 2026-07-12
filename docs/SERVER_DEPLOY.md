# Server Deploy Notes

Общая памятка для Codex по серверу, путям проектов и безопасному деплою.

## Главный VPS

- SSH: `root@178.104.156.114`
- ОС/хост по последней проверке: `ubuntu-4gb-nbg1-1`
- Docker установлен.
- Docker Compose на сервере сейчас доступен: `docker compose version`
- Базовая директория проектов: `/opt`

Проверка доступа:

```bash
ssh root@178.104.156.114 "hostname && docker --version && docker compose version && ls -la /opt"
```

## Общие правила

- Сначала диагностика, потом изменения.
- Не печатать приватные ключи, токены, пароли и содержимое `.env`.
- Если пользователь прислал секрет в чат, не повторять его в ответе и не вставлять в логи/URL-проверки.
- Для Telegram tokens запрещено включать `httpx/httpcore` INFO-логи: URL Telegram Bot API содержит token.
- Проверять секреты только косвенно: `grep -c`/masked pattern/status code, без вывода самого значения.
- Если секрет уже попал в чат, terminal output или application logs, считать его скомпрометированным и ротировать.
- Не менять `.env` на сервере без явного запроса.
- Не делать destructive-команды без явного подтверждения: `docker compose down -v`, `rm -rf`, `git reset --hard`, очистка volumes/БД.
- Для уже настроенных production-проектов предпочтителен деплой через GitHub Actions/обычный проектный скрипт, а не ручные правки на VPS.
- Ручные VPS-правки допустимы только как аварийный targeted fix или когда пользователь прямо попросил загрузить новый standalone-проект.

## Известные проекты на VPS

### Kinoroom / RoomPilot

- Локально: `D:\projects\Kinoroom`
- На VPS: `/opt/kinoroom`
- SSH: `root@178.104.156.114`
- Канонический деплой: `git push origin main` -> GitHub Actions -> SSH на VPS -> `docker compose`.
- GitHub Actions workflow: `.github/workflows/deploy.yml`
- Секреты Actions:
  - `VPS_HOST=178.104.156.114`
  - `VPS_USER=root`
  - `VPS_SSH_KEY=<private key in GitHub secrets>`
- Live URLs:
  - `https://roompilot.kz`
  - `https://roompilot.kz/admin`
  - `https://roompilot.kz/setup.html`
  - `https://app.roompilot.kz`
  - `https://app.roompilot.kz/api/v1/`
  - `https://roompilot.kz/api/v1/`
  - `https://roompilot.kz/docs`

Нормальная схема деплоя Kinoroom:

```bash
cd D:\projects\Kinoroom
.\deploy.ps1 "описание изменений"
```

Что делает workflow на VPS:

```bash
cd /opt/kinoroom
git fetch origin
git reset --hard origin/main
docker compose up -d --build --no-recreate db
docker compose run --rm migrate
docker compose up -d --build api nginx
docker compose restart nginx
```

Контейнеры Kinoroom:

- API: `kinoroom-api-1`, внутренний порт `:8000`
- Nginx: `kinoroom-nginx-1`, внешний порт VPS `8001 -> 80`
- PostgreSQL: `kinoroom-db-1`, `127.0.0.1:5433 -> 5432`

Команды диагностики:

```bash
ssh root@178.104.156.114 "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
ssh root@178.104.156.114 "docker logs kinoroom-api-1 --tail=100"
ssh root@178.104.156.114 "docker logs kinoroom-nginx-1 --tail=100"
```

Важно:

- Не использовать старые временные Cloudflare tunnel URLs как канонические.
- Прямой браузерный доступ `http://178.104.156.114:8001` может блокироваться провайдером; использовать домены.

### Trading Bot

- На VPS: `/opt/trading-bot/TraidingBotLLM`
- Обёртка/логи деплоя: `/opt/trading-bot/auto_deploy.sh`, `/opt/trading-bot/deploy.log`
- Сервис в compose: `trading-bot`
- Container name: `trading-bot`
- Compose volumes:
  - `./data:/app/data`
  - `./logs:/app/logs`
- Restart policy: `unless-stopped`

Команды диагностики:

```bash
ssh root@178.104.156.114 "docker ps --filter name=trading-bot"
ssh root@178.104.156.114 "docker logs trading-bot --tail=100"
ssh root@178.104.156.114 "tail -100 /opt/trading-bot/deploy.log"
```

Старый auto deploy проверяет ветку `master`, делает `git pull origin master`, при ошибке может выполнить `git reset --hard origin/master`, затем перезапускает `systemctl restart tradingbot`. Перед использованием обязательно проверить текущее состояние проекта и сервисов.

### Arbitrazh Bybit Paper Bot

- Локально: `D:\projects\Arbitrazh`
- Рекомендуемый путь на VPS: `/opt/arbitrazh-paper-bot`
- Режим: paper-trading only.
- Exchange API keys не нужны.
- Private/trade endpoints запрещены hard guard-ом в коде.
- Docker Compose поднимает:
  - `postgres`
  - `app` на порту `8000`

Первичный ручной deploy нового standalone-проекта:

```bash
ssh root@178.104.156.114 "mkdir -p /opt/arbitrazh-paper-bot"
# загрузить исходники, кроме .git/.venv/__pycache__/.pytest_cache
ssh root@178.104.156.114 "cd /opt/arbitrazh-paper-bot && cp .env.example .env && docker compose up -d --build"
```

Проверка:

```bash
ssh root@178.104.156.114 "cd /opt/arbitrazh-paper-bot && docker compose ps"
ssh root@178.104.156.114 "curl -fsS http://127.0.0.1:8000/health"
ssh root@178.104.156.114 "cd /opt/arbitrazh-paper-bot && docker compose logs app --tail=100"
```

Если порт `8000` уже занят, изменить внешний порт сервиса `app` в `docker-compose.yml`, например `8010:8000`.

## Быстрый server inventory

По последней проверке в `/opt` есть:

- `/opt/kinoroom`
- `/opt/trading-bot`
- `/opt/kaspi-notifier`
- `/opt/santeh`
- `/opt/medical-radar`
- `/opt/iphone-activity`

Перед загрузкой нового проекта проверять:

```bash
ssh root@178.104.156.114 "ls -la /opt && docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
```
