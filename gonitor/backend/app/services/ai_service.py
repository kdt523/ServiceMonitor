"""
AI Chat service — Gonitor Copilot powered by Google Gemini (gemini-2.5-flash).

Design decisions:
  1. Sliding window (MAX_HISTORY_TURNS) — prevents quadratic token cost growth.
     The frontend holds the full conversation; we only send the tail to the model.
  2. Session key isolation — each (host_id, service_type) pair is a separate session.
     The backend is stateless; session ownership lives in the frontend.
  3. Fresh context injection — monitoring context is prepended to EVERY last user
     message, not just the first. This ensures stale state never leaks into answers.
  4. Structured error returns — no raised exceptions; frontend always gets a dict.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sliding window size
# 10 turns = 10 user + 10 assistant = 20 messages sent to model per request.
# Without this, token cost grows as a triangle number (1+2+3+...+N) × msg_size.
# With 10-turn window: ~95% cheaper than unbounded history at 50 messages.
# ---------------------------------------------------------------------------
MAX_HISTORY_TURNS = 10

# ---------------------------------------------------------------------------
# System prompt — seeds every conversation with Gonitor domain knowledge
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are Gonitor Assistant — an expert AI copilot embedded inside Gonitor, \
a self-hosted, production-grade uptime monitoring platform.

━━━ WHAT GONITOR MONITORS ━━━
Gonitor monitors hosts across four service types:

• http  — Validates HTTP 200-399. Optionally checks for keyword.
• https — Validates HTTPS 200-399 and TLS handshake. Optionally checks for keyword.
• ssl   — Checks SSL certificate expiration (Healthy >30 days, Warning 7-30 days, Problem <7 days).
• tcp   — Raw TCP port connectivity check.
• ping  — ICMP echo request. Success = reply received. Failure = unreachable or blocked.
• dns   — DNS hostname resolution via getaddrinfo. Success = resolves to IP.
• ssh   — TCP connect to port 22 (SSH daemon).
• ftp   — TCP connect to port 21 (FTP daemon).
• smtp  — TCP connect to port 587 + 220 greeting banner grab.

━━━ STATUS MEANINGS ━━━
• healthy  — Check passed
• warning  — SSL cert expires in 7–30 days (SSL checks only)
• problem  — Check failed for any reason
• pending  — Service was just added or re-enabled; no check has run yet

━━━ ERROR MESSAGE DICTIONARY ━━━
HTTP/HTTPS:
- HTTP 4xx (401, 403, 404): Client error. The resource doesn't exist, requires auth, or IP is blocked (e.g. Cloudflare 403).
- HTTP 5xx (500, 502, 503, 504): Server error. The backend crashed, is down, or the reverse proxy timed out.
- Connection timed out: The server is ignoring traffic, overloaded, or firewall is dropping packets (no RST sent).
- Connection refused: The server actively rejected the connection (RST sent) — nothing is listening on the port.
- Keyword '[word]' not found: The status was 200 OK, but the expected string was missing from the response body.

SSL:
- [SSL: CERTIFICATE_VERIFY_FAILED]: Expired cert, self-signed, untrusted CA, or missing intermediate certs.
- ssl_days_remaining < 7: Certificate expires very soon. Needs immediate renewal.

Network / Lower Level (Ping, DNS, TCP, SSH, FTP, SMTP):
- Ping failed — host unreachable: ICMP is blocked by a firewall, routing is down, or server is offline.
- DNS failed: Name doesn't exist (NXDOMAIN) or DNS server is down (SERVFAIL).
- Unexpected SMTP banner: Connected to the port, but the server didn't reply with "220" (might not be an SMTP server).
- TCP Connection refused: No service is listening on the specified port.

━━━ HOW TO RESPOND ━━━
1. Always identify the root cause first, then give actionable next steps.
2. Keep your FIRST reply concise — 3 to 5 sentences — then offer to elaborate.
3. Always relate your answer to the specific host, URL, service type, and error in the context provided.
4. Briefly define any technical terms that a non-expert might not know.
5. If the status is "healthy" and the user asks why something worked, explain what the check validated.
6. Do not make up error details — if the error message isn't in the context, say so clearly.
7. For SSL expiry warnings, always mention the days remaining and urgency.
8. Be direct and professional — no filler phrases like "Great question!" or "Certainly!".
"""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_context_block(context: Optional[dict]) -> str:
    """
    Build a monitoring context preamble injected into the CURRENT user message.

    Injected fresh on every API call (not just the first message) so the model
    always sees the current check state, not a stale snapshot from message #1.
    """
    if not context:
        return ""
    parts = []
    if context.get("host_name"):
        parts.append(f"Host: {context['host_name']}")
    if context.get("url"):
        parts.append(f"URL: {context['url']}")
    if context.get("service_type"):
        parts.append(f"Service type: {context['service_type'].upper()}")
    if context.get("status"):
        parts.append(f"Current status: {context['status'].upper()}")
    if context.get("response_time_ms") is not None:
        parts.append(f"Response time: {context['response_time_ms']}ms")
    if context.get("error_message"):
        parts.append(f"Error message: {context['error_message']}")
    if not parts:
        return ""
    return "[Current Monitoring Context]\n" + "\n".join(parts) + "\n\n"


def _get_windowed_history(messages: list[dict]) -> list[dict]:
    """
    Return only the last MAX_HISTORY_TURNS * 2 messages.

    Token cost without windowing grows as a triangle number:
      N messages → N*(N+1)/2 × avg_msg_tokens total input paid over the session.
    With a 10-turn window (20 msgs), cost is capped at 55 × avg_msg_tokens.
    The UI still displays the FULL conversation — only the API call is trimmed.
    """
    window_size = MAX_HISTORY_TURNS * 2  # user + assistant pairs
    return messages[-window_size:] if len(messages) > window_size else messages


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

async def chat(
    messages: list[dict],
    context: Optional[dict] = None,
    session_key: str = "",
) -> dict:
    """
    Send a windowed, context-injected conversation to Gemini (gemini-2.5-flash).

    Args:
        messages    : Full conversation history for THIS session from the frontend.
                      The function applies a sliding window before sending to the API.
                      Shape: [{"role": "user"|"assistant", "content": str}, ...]
        context     : Current monitoring state for the host+service being discussed.
                      Keys: host_name, url, service_type, status, error_message, response_time_ms
        session_key : Unique identifier = f"{host_id}_{service_type}" e.g. "42_https".
                      Echoed back in the response for frontend session routing.

    Returns:
        dict with:
            "reply"       : str  — Gemini's response text
            "session_key" : str  — echoed for frontend routing
            "turns_sent"  : int  — number of history turns sent to API (after windowing)
    """
    try:
        from google import genai
        from google.genai import types
        from app.config import get_settings

        settings = get_settings()

        # ── Guard: API key required ────────────────────────────────────────
        if not settings.gemini_api_key:
            return {
                "reply": "⚠️ AI chat is not configured. Add `GEMINI_API_KEY` to your `.env` file.",
                "session_key": session_key,
                "turns_sent": 0,
            }

        if not messages:
            return {
                "reply": "⚠️ No messages provided.",
                "session_key": session_key,
                "turns_sent": 0,
            }

        # Initialize the Client
        client = genai.Client(api_key=settings.gemini_api_key)

        # ── Apply sliding window to history (all but the last/current message) ──
        history_only = messages[:-1]  # exclude the current (last) user message
        windowed = _get_windowed_history(history_only)
        turns_sent = len(windowed) // 2  # rough turn count (user+model pairs)

        # ── Build Gemini history list (role: "user" | "model") ────────────
        contents = []
        for msg in windowed:
            # Gemini uses "model" for assistant, not "assistant"
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # ── Inject fresh context into the current (last) user message ─────
        context_block = _build_context_block(context)
        current_content = context_block + messages[-1]["content"]
        contents.append({"role": "user", "parts": [{"text": current_content}]})

        # ── Generate content using client.aio for async execution ─────────
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
            ),
        )

        return {
            "reply": response.text,
            "session_key": session_key,
            "turns_sent": turns_sent,
        }

    except Exception as exc:
        error_str = str(exc)

        # Map common errors to friendly messages
        if "API_KEY_INVALID" in error_str or "API key" in error_str.lower():
            msg = "⚠️ Invalid Gemini API key. Check your `.env` file."
        elif "quota" in error_str.lower() or "rate" in error_str.lower() or "429" in error_str:
            msg = "⚠️ Gemini rate limit reached. Please wait a moment and try again."
        elif "connect" in error_str.lower() or "network" in error_str.lower():
            msg = "⚠️ Could not reach the Gemini AI service. Check your network connection."
        else:
            msg = f"⚠️ AI assistant error: {error_str}"
            logger.error("AI chat error (session=%s): %s", session_key, exc)

        return {
            "reply": msg,
            "session_key": session_key,
            "turns_sent": 0,
        }
