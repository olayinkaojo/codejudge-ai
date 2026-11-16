"""PostgreSQL-atomic admission limits. No passwords, raw usernames or IPs are stored."""

import hashlib
import hmac
import ipaddress
import logging
import math
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import case, delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import get_settings
from app.models import AuthRateBucket, AuthRateSecret

logger = logging.getLogger("codejudge.security")


def address(value):
    ip = ipaddress.ip_address(value)
    return getattr(ip, "ipv4_mapped", None) or ip


def network_identity(request, settings):
    try:
        peer = address(request.client.host)
    except (ValueError, AttributeError):
        return "unresolved-peer"  # Shared fail-safe bucket, not a header-derived identity.
    trusted = [
        ipaddress.ip_network(v.strip()) for v in settings.auth_trusted_proxy_cidrs.split(",") if v.strip()
    ]

    def is_trusted(ip):
        return any(ip.version == net.version and ip in net for net in trusted)

    forwarded = request.headers.get("x-forwarded-for", "")
    if is_trusted(peer) and forwarded and len(forwarded) <= 512:
        parts = forwarded.split(",")
        if len(parts) <= 8:
            try:
                chain = [address(part.strip()) for part in parts] + [peer]
                while len(chain) > 1 and is_trusted(chain[-1]):
                    chain.pop()
                peer = chain[-1]
            except ValueError:
                pass  # Malformed/oversized chains use the actual peer, never a guessed address.
    if peer.version == 6:
        return str(ipaddress.ip_network(f"{peer}/64", strict=False))
    return str(peer)


def admit(db, request, username, action):
    settings = get_settings()
    dialect = db.bind.dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise HTTPException(503, "Authentication temporarily unavailable")
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    if dialect == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        now = db.scalar(select(text("clock_timestamp()")))
    else:
        now = datetime.now(timezone.utc)  # SQLite is for unit tests only.
    db.execute(
        insert(AuthRateSecret)
        .values(id=1, secret=secrets.token_hex(32))
        .on_conflict_do_nothing(index_elements=["id"])
    )
    secret = db.get(AuthRateSecret, 1).secret.encode()
    network = network_identity(request, settings)
    policies = [("global", "all", 60, settings.auth_global_per_minute)]
    if action == "register":
        policies += [
            ("registration", "all", 60, settings.auth_register_per_minute),
            ("network-registration", network, 3600, settings.auth_network_registrations),
        ]
    else:
        policies += [
            ("network-login", network, 300, settings.auth_network_logins),
            ("pair-login", network + ":" + username, 300, settings.auth_pair_logins),
        ]
    buckets = []
    for scope, identity, seconds, cap in policies:
        key = hmac.new(secret, f"{scope}:{identity}".encode(), hashlib.sha256).hexdigest()
        reset = datetime.fromtimestamp((int(now.timestamp()) // seconds + 1) * seconds, timezone.utc)
        buckets.append((key, scope, cap, reset))
    blocked = []
    # Fixed global gates come first: rejected traffic cannot allocate unlimited
    # per-username/source rows and exhaust a small PostgreSQL instance.
    ordered = sorted(
        buckets,
        key=lambda item: (0 if item[1] == "global" else 1 if item[1] == "registration" else 2, item[0]),
    )
    for key, scope, cap, reset in ordered:
        statement = insert(AuthRateBucket).values(key=key, hits=1, reset_at=reset)
        count, expiry = db.execute(
            statement.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "hits": case(
                        (AuthRateBucket.reset_at <= now, 1),
                        (AuthRateBucket.hits < cap + 1, AuthRateBucket.hits + 1),
                        else_=AuthRateBucket.hits,
                    ),
                    "reset_at": case((AuthRateBucket.reset_at <= now, reset), else_=AuthRateBucket.reset_at),
                },
            ).returning(AuthRateBucket.hits, AuthRateBucket.reset_at)
        ).one()
        if count > cap:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            blocked.append((scope, max(1, math.ceil((expiry - now).total_seconds()))))
            break
    expired = select(AuthRateBucket.key).where(AuthRateBucket.reset_at < now - timedelta(days=1)).limit(100)
    db.execute(delete(AuthRateBucket).where(AuthRateBucket.key.in_(expired)))
    db.commit()  # Admission survives failed credentials, process restarts and parallel replicas.
    if blocked:
        logger.warning("auth_rate_limited action=%s scope=%s", action, blocked[0][0])
        raise HTTPException(
            429,
            "Too many authentication attempts. Try again later.",
            headers={"Retry-After": str(max(delay for _, delay in blocked))},
        )
    logger.info("auth_admitted action=%s", action)
