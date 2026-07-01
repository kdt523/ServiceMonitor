"""
Seed script to load websites that have known issues for monitoring testing.
Includes: HTTP-only sites, bad SSL, expired certs, slow/unreliable sites, etc.
"""
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionFactory
from app.models.user import User
from app.models.host import Host
from app.models.host_service import HostService
from app.services.auth_service import hash_password

# Sites with known issues:
# - HTTP only (no HTTPS) → HTTP check passes, HTTPS fails
# - Expired / self-signed SSL → SSL check triggers warning/critical
# - Redirect-only domains (HTTP → HTTPS, so bare HTTP returns 301 not 200)
# - Sites known to be unreliable or rate-limit aggressively
# - Intentional test/dummy bad URLs

PROBLEMATIC_WEBSITES = [
    # ── HTTP-only sites (no HTTPS at all) ─────────────────────────────────────
    {
        "name": "Neverssl",
        "url": "http://neverssl.com",
        "canonical_name": "neverssl.com",
        "location": "Global",
        "note": "Intentionally HTTP-only. HTTPS check will fail.",
        "services": ["http", "https", "ssl", "ping", "dns"],
    },
    {
        "name": "HTTP Example",
        "url": "http://example.com",
        "canonical_name": "example.com",
        "location": "Global",
        "note": "Plain HTTP. No SSL. HTTPS/SSL checks will fail.",
        "services": ["http", "https", "ssl"],
    },
    {
        "name": "Testingmachines HTTP",
        "url": "http://testingmachines.com",
        "canonical_name": "testingmachines.com",
        "location": "US-East",
        "note": "HTTP-only hosting. SSL check will fail.",
        "services": ["http", "https", "ssl"],
    },

    # ── Sites with expired / self-signed SSL ──────────────────────────────────
    {
        "name": "Expired SSL Test (Badssl)",
        "url": "https://expired.badssl.com",
        "canonical_name": "expired.badssl.com",
        "location": "Global",
        "note": "Deliberately expired SSL certificate. SSL check → critical.",
        "services": ["https", "ssl"],
    },
    {
        "name": "Self-Signed SSL Test (Badssl)",
        "url": "https://self-signed.badssl.com",
        "canonical_name": "self-signed.badssl.com",
        "location": "Global",
        "note": "Self-signed certificate. SSL check → warning/problem.",
        "services": ["https", "ssl"],
    },
    {
        "name": "Wrong Host SSL Test (Badssl)",
        "url": "https://wrong.host.badssl.com",
        "canonical_name": "wrong.host.badssl.com",
        "location": "Global",
        "note": "Certificate hostname mismatch. SSL check → problem.",
        "services": ["https", "ssl"],
    },
    {
        "name": "Untrusted Root SSL (Badssl)",
        "url": "https://untrusted-root.badssl.com",
        "canonical_name": "untrusted-root.badssl.com",
        "location": "Global",
        "note": "Untrusted root CA. SSL check → problem.",
        "services": ["https", "ssl"],
    },
    {
        "name": "RC4 Cipher SSL (Badssl)",
        "url": "https://rc4.badssl.com",
        "canonical_name": "rc4.badssl.com",
        "location": "Global",
        "note": "Weak RC4 cipher. HTTPS check will likely fail handshake.",
        "services": ["https", "ssl"],
    },

    # ── HTTP → HTTPS redirects (HTTP check returns 301, not 200) ──────────────
    {
        "name": "GitHub (HTTP redirect)",
        "url": "http://github.com",
        "canonical_name": "github.com",
        "location": "Global",
        "note": "HTTP returns 301 redirect to HTTPS. HTTP check → problem.",
        "services": ["http"],
    },
    {
        "name": "Stripe (HTTP redirect)",
        "url": "http://stripe.com",
        "canonical_name": "stripe.com",
        "location": "US-East",
        "note": "HTTP returns 301. HTTP check will fail if not following redirects.",
        "services": ["http"],
    },
    {
        "name": "Cloudflare (HTTP redirect)",
        "url": "http://cloudflare.com",
        "canonical_name": "cloudflare.com",
        "location": "Global",
        "note": "HTTP → HTTPS redirect. HTTP check → warning.",
        "services": ["http"],
    },

    # ── Non-existent / unreachable hosts ──────────────────────────────────────
    {
        "name": "Dead Domain",
        "url": "http://this-domain-does-not-exist-at-all-xyz.com",
        "canonical_name": "this-domain-does-not-exist-at-all-xyz.com",
        "location": "Unknown",
        "note": "DNS will fail. All checks → problem.",
        "services": ["http", "https", "ssl"],
    },
    {
        "name": "Localhost (unreachable externally)",
        "url": "http://localhost:9999",
        "canonical_name": "localhost",
        "location": "Local",
        "note": "Only reachable inside container. External check → problem.",
        "services": ["http"],
    },
    {
        "name": "Private IP (unreachable)",
        "url": "http://192.168.1.1",
        "canonical_name": "192.168.1.1",
        "location": "Local",
        "note": "Private subnet IP. Will timeout externally → problem.",
        "services": ["http"],
    },

    # ── Sites that return non-200 status codes ─────────────────────────────────
    {
        "name": "SMTP Timeout Test (Port 587)",
        "url": "http://smtp-timeout.badssl.com",
        "canonical_name": "example.com",
        "location": "Global",
        "note": "SMTP banner grab should timeout.",
        "services": ["smtp", "tcp"],
    },
    {
        "name": "HTTP 404 Test (Httpstat.us)",
        "url": "https://httpstat.us/404",
        "canonical_name": "httpstat.us",
        "location": "Global",
        "note": "Always returns HTTP 404. HTTP/HTTPS check → problem.",
        "services": ["https"],
    },
    {
        "name": "HTTP 500 Test (Httpstat.us)",
        "url": "https://httpstat.us/500",
        "canonical_name": "httpstat.us",
        "location": "Global",
        "note": "Always returns HTTP 500. HTTP/HTTPS check → problem.",
        "services": ["https"],
    },
    {
        "name": "HTTP 503 Test (Httpstat.us)",
        "url": "https://httpstat.us/503",
        "canonical_name": "httpstat.us",
        "location": "Global",
        "note": "Simulates service unavailable. Check → problem.",
        "services": ["https"],
    },
    {
        "name": "HTTP 429 Rate Limited (Httpstat.us)",
        "url": "https://httpstat.us/429",
        "canonical_name": "httpstat.us",
        "location": "Global",
        "note": "Always returns 429 Too Many Requests → problem.",
        "services": ["https"],
    },

    # ── Slow / timeout-prone sites ─────────────────────────────────────────────
    {
        "name": "Slow Response (Httpstat.us 200 + delay)",
        "url": "https://httpstat.us/200?sleep=10000",
        "canonical_name": "httpstat.us",
        "location": "Global",
        "note": "Intentional 10s delay. Will timeout if checker has <10s timeout.",
        "services": ["https"],
    },
    {
        "name": "Postman Echo (slow)",
        "url": "https://httpbin.org/delay/8",
        "canonical_name": "httpbin.org",
        "location": "Global",
        "note": "8-second artificial delay. Likely to timeout in fast checkers.",
        "services": ["https"],
    },

    # ── SSL expiring soon (warning zone) ──────────────────────────────────────
    {
        "name": "SSL Nearly Expired (Badssl)",
        "url": "https://1000-sans.badssl.com",
        "canonical_name": "1000-sans.badssl.com",
        "location": "Global",
        "note": "Unusual certificate (1000 SANs). May trigger SSL warnings.",
        "services": ["https", "ssl"],
    },
    {
        "name": "Mixed Content (Badssl)",
        "url": "https://mixed.badssl.com",
        "canonical_name": "mixed.badssl.com",
        "location": "Global",
        "note": "Mixed HTTP+HTTPS content. SSL technically valid but insecure.",
        "services": ["https", "ssl"],
    },

    # ── Sites with aggressive bot-blocking (checks may return 403) ────────────
    {
        "name": "Cloudflare-protected (G2)",
        "url": "https://www.g2.com",
        "canonical_name": "www.g2.com",
        "location": "US-East",
        "note": "Aggressive Cloudflare bot challenge. Monitor check may return 403.",
        "services": ["https", "ssl"],
    },
    {
        "name": "Distil-protected (Imperva)",
        "url": "https://www.zillow.com",
        "canonical_name": "www.zillow.com",
        "location": "US-West",
        "note": "Bot protection may return 403/503 to automated checkers.",
        "services": ["https", "ssl"],
    },
]


async def main():
    async with AsyncSessionFactory() as session:
        # 1. Get or create an admin user
        result = await session.execute(select(User).order_by(User.id))
        user = result.scalars().first()

        if not user:
            print("No users found. Creating a default admin user...")
            user = User(
                email="admin@gonitor.com",
                password_hash=hash_password("adminpassword"),
                first_name="Admin",
                last_name="User",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            print(f"Created user: {user.email} (Password: adminpassword)")
        else:
            print(f"Using existing user: {user.email}")

        # 2. Add problematic websites
        added_count = 0
        for web in PROBLEMATIC_WEBSITES:
            exist_result = await session.execute(
                select(Host).where(Host.url == web["url"])
            )
            existing_host = exist_result.scalars().first()

            if existing_host:
                print(f"Host '{web['name']}' already exists, skipping.")
                continue

            host = Host(
                user_id=user.id,
                name=web["name"],
                url=web["url"],
                canonical_name=web["canonical_name"],
                location=web["location"],
                is_active=True,
            )
            session.add(host)
            await session.flush()

            for stype in web["services"]:
                service = HostService(
                    host_id=host.id,
                    service_type=stype,
                    is_active=True,
                    interval_minutes=5,
                    status="pending",
                )
                session.add(service)

            added_count += 1
            print(f"[{web['note']}]")
            print(f"  Queued: '{web['name']}' -> {web['url']}")

        await session.commit()
        print(f"\nSeeding completed! Added {added_count} problematic hosts.")


if __name__ == "__main__":
    asyncio.run(main())