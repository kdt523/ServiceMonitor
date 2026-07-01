# Gonitor 🔍

> **Production-quality uptime monitoring service** — monitor URLs and TCP hosts, get real-time alerts via Pusher, and view everything on a live dashboard.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 + FastAPI |
| Database | PostgreSQL 15 + SQLAlchemy async ORM |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Real-time | Pusher WebSockets |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| HTTP checks | httpx (async) |
| TCP checks | asyncio.open_connection |
| Templating | Jinja2 + Bootstrap 5 |
| Migrations | Alembic |

---

## Quick Start (Docker)

```bash
# 1. Copy and fill in your credentials
cp .env.example .env
# Edit .env — add your Pusher credentials and a strong SECRET_KEY

# 2. Start the stack
docker-compose up --build

# 3. Open the dashboard
open http://localhost:8000
```

---

## Quick Start (Local Dev)

### Prerequisites
- Python 3.11+
- PostgreSQL running locally

```bash
cd gonitor

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your DB connection and Pusher credentials

# Run database migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload --port 8000
```

The app auto-creates all DB tables on startup (via `Base.metadata.create_all`), so Alembic is optional for development.

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Async PostgreSQL URL | `postgresql+asyncpg://user:pass@localhost/db` |
| `SECRET_KEY` | JWT signing secret (keep secret!) | random 32+ char string |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session duration | `1440` (24h) |
| `PUSHER_APP_ID` | Pusher App ID | from pusher.com dashboard |
| `PUSHER_KEY` | Pusher Key | from pusher.com dashboard |
| `PUSHER_SECRET` | Pusher Secret | from pusher.com dashboard |
| `PUSHER_CLUSTER` | Pusher cluster | `ap2`, `eu`, `us2`, etc. |

Get free Pusher credentials at [pusher.com](https://pusher.com) (free plan supports 100 simultaneous connections).

---

## Project Structure

```
gonitor/
├── app/
│   ├── main.py              # App factory + lifespan
│   ├── config.py            # Settings (pydantic-settings)
│   ├── database.py          # Async SQLAlchemy engine
│   ├── dependencies.py      # Auth dependency
│   ├── models/              # ORM models (User, Resource, CheckLog)
│   ├── schemas/             # Pydantic schemas
│   ├── routers/             # FastAPI routers
│   ├── services/            # Business logic
│   │   ├── auth_service.py  # JWT + bcrypt
│   │   ├── health_checker.py # HTTP + TCP checks
│   │   ├── scheduler.py     # APScheduler job management
│   │   └── pusher_service.py # Pusher events
│   └── templates/           # Jinja2 HTML
├── static/js/dashboard.js   # Pusher + DOM updates
├── alembic/                 # DB migrations
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## API Endpoints

### Auth
| Method | Path | Description |
|--------|------|-------------|
| GET | `/login` | Login page |
| POST | `/login` | Authenticate, set cookie |
| GET | `/register` | Registration page |
| POST | `/register` | Create account |
| POST | `/logout` | Clear session |

### Resources
| Method | Path | Description |
|--------|------|-------------|
| GET | `/resources` | List user's resources (JSON) |
| POST | `/resources` | Create resource |
| GET | `/resources/{id}` | Get resource |
| PUT | `/resources/{id}` | Update resource |
| DELETE | `/resources/{id}` | Delete resource |
| GET | `/resources/{id}/logs` | Check history (last 50) |
| POST | `/resources/{id}/check-now` | Immediate health check |

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirect to dashboard |
| GET | `/dashboard` | Main dashboard |
| GET | `/resources/{id}/detail` | Resource detail + history |

---

## Testing the Real-time Flow

1. Register and log in
2. Add a resource: `https://thisurldoesnotexist12345.com` (interval: 1 min)
3. Click **Check Now** — the status badge turns 🔴 red instantly
4. A Pusher toast notification appears in the top-right corner
5. Update the URL to `https://google.com` and click Check Now again
6. Status changes to 🟢 UP with a green toast

---

## Alembic Migrations

```bash
# Generate a new migration after model changes
alembic revision --autogenerate -m "describe_change"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

---

## Architecture Notes

- **Scheduler isolation**: Each APScheduler job opens its own DB session — jobs run outside the request context.
- **Status change detection**: Pusher events only fire when `old_status != new_status`, preventing alert spam.
- **JWT in cookies**: `HttpOnly + SameSite=Lax` cookies — no XSS risk from localStorage.
- **TCP URL format**: Store as `tcp://hostname:port`; the health checker parses it automatically.
- **Coalescing**: `coalesce=True` + `misfire_grace_time=30s` prevent job pile-up under load.
