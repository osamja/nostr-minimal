import asyncio
import json
import hashlib
import os

import aiosqlite
import secp256k1
import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers

# Config via env vars
RELAY_DB_PATH = os.environ.get("RELAY_DB_PATH", "relay.db")
RELAY_OWNER_PUBKEY = os.environ.get("RELAY_OWNER_PUBKEY", "")
RELAY_NAME = os.environ.get("RELAY_NAME", "nostr-minimal")
RELAY_DESCRIPTION = os.environ.get("RELAY_DESCRIPTION", "A minimal personal Nostr relay")
RELAY_CONTACT = os.environ.get("RELAY_CONTACT", "")

# Active subscriptions: {websocket: {sub_id: [filter_dict, ...]}}
SUBSCRIPTIONS = {}

DB = None


async def init_db():
    global DB
    DB = await aiosqlite.connect(RELAY_DB_PATH)
    DB.row_factory = aiosqlite.Row
    await DB.execute("PRAGMA journal_mode=WAL")
    await DB.execute("PRAGMA synchronous=NORMAL")
    await DB.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            pubkey TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            kind INTEGER NOT NULL,
            tags TEXT NOT NULL,
            content TEXT NOT NULL,
            sig TEXT NOT NULL
        )
    """)
    await DB.execute("CREATE INDEX IF NOT EXISTS idx_pubkey ON events(pubkey)")
    await DB.execute("CREATE INDEX IF NOT EXISTS idx_kind ON events(kind)")
    await DB.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON events(created_at)")
    await DB.commit()


def verify_event(event):
    serialized = json.dumps([
        0,
        event["pubkey"],
        event["created_at"],
        event["kind"],
        event["tags"],
        event["content"],
    ], separators=(',', ':'), ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    if digest != event.get("id"):
        return False
    try:
        pubkey_bytes = bytes.fromhex(event["pubkey"])
        sig_bytes = bytes.fromhex(event["sig"])
        event_id_bytes = bytes.fromhex(event["id"])

        for prefix in [0x02, 0x03]:
            try:
                compressed_pubkey = bytes([prefix]) + pubkey_bytes
                pubkey_obj = secp256k1.PublicKey(compressed_pubkey, raw=True)
                sig_obj = secp256k1.ECDSA().ecdsa_deserialize_compact(sig_bytes)
                pubkey_obj.ecdsa_verify(event_id_bytes, sig_obj, raw=True)
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def event_matches_filter(event, f):
    if "ids" in f:
        if not any(event["id"].startswith(prefix) for prefix in f["ids"]):
            return False
    if "authors" in f:
        if not any(event["pubkey"].startswith(prefix) for prefix in f["authors"]):
            return False
    if "kinds" in f:
        if event["kind"] not in f["kinds"]:
            return False
    if "since" in f:
        if event["created_at"] < f["since"]:
            return False
    if "until" in f:
        if event["created_at"] > f["until"]:
            return False
    # NIP-01 #e and #p tag filters
    for key, values in f.items():
        if key.startswith("#") and len(key) == 2:
            tag_name = key[1]
            event_tag_values = [t[1] for t in event["tags"] if len(t) >= 2 and t[0] == tag_name]
            if not any(v in event_tag_values for v in values):
                return False
    return True


async def query_events(filters):
    """Query stored events matching any of the given filters."""
    results = []
    for f in filters:
        clauses = []
        params = []

        if "ids" in f:
            id_clauses = []
            for prefix in f["ids"]:
                id_clauses.append("id LIKE ?")
                params.append(prefix + "%")
            clauses.append("(" + " OR ".join(id_clauses) + ")")

        if "authors" in f:
            author_clauses = []
            for prefix in f["authors"]:
                author_clauses.append("pubkey LIKE ?")
                params.append(prefix + "%")
            clauses.append("(" + " OR ".join(author_clauses) + ")")

        if "kinds" in f:
            placeholders = ",".join("?" for _ in f["kinds"])
            clauses.append(f"kind IN ({placeholders})")
            params.extend(f["kinds"])

        if "since" in f:
            clauses.append("created_at >= ?")
            params.append(f["since"])

        if "until" in f:
            clauses.append("created_at <= ?")
            params.append(f["until"])

        where = " AND ".join(clauses) if clauses else "1=1"
        limit = min(f.get("limit", 500), 500)

        query = f"SELECT * FROM events WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with DB.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                event = {
                    "id": row["id"],
                    "pubkey": row["pubkey"],
                    "created_at": row["created_at"],
                    "kind": row["kind"],
                    "tags": json.loads(row["tags"]),
                    "content": row["content"],
                    "sig": row["sig"],
                }
                # Apply tag filters in Python (complex to do in SQL)
                if event_matches_filter(event, f):
                    results.append(event)

    # Deduplicate by event id
    seen = set()
    deduped = []
    for ev in results:
        if ev["id"] not in seen:
            seen.add(ev["id"])
            deduped.append(ev)
    return deduped


async def store_event(event):
    try:
        cursor = await DB.execute(
            "INSERT OR IGNORE INTO events (id, pubkey, created_at, kind, tags, content, sig) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event["id"], event["pubkey"], event["created_at"], event["kind"],
             json.dumps(event["tags"]), event["content"], event["sig"]),
        )
        await DB.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"error storing event: {e}")
        return False


async def notify_subscribers(event):
    """Push a new event to all matching live subscriptions."""
    for ws, subs in list(SUBSCRIPTIONS.items()):
        for sub_id, filters in subs.items():
            if any(event_matches_filter(event, f) for f in filters):
                try:
                    await ws.send(json.dumps(["EVENT", sub_id, event]))
                except Exception:
                    pass


async def handler(websocket):
    SUBSCRIPTIONS[websocket] = {}
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                if not isinstance(msg, list) or len(msg) < 2:
                    continue

                if msg[0] == "EVENT":
                    event = msg[1]

                    # Owner restriction
                    if RELAY_OWNER_PUBKEY and event.get("pubkey") != RELAY_OWNER_PUBKEY:
                        await websocket.send(json.dumps(
                            ["OK", event.get("id", ""), False, "blocked: only owner can publish"]
                        ))
                        continue

                    if verify_event(event):
                        stored = await store_event(event)
                        await websocket.send(json.dumps(["OK", event["id"], True, ""]))
                        if stored:
                            await notify_subscribers(event)
                    else:
                        await websocket.send(json.dumps(
                            ["OK", event.get("id", ""), False, "invalid: signature verification failed"]
                        ))

                elif msg[0] == "REQ":
                    sub_id = msg[1]
                    filters = msg[2:] if len(msg) > 2 else [{}]

                    # Store subscription for live updates
                    SUBSCRIPTIONS[websocket][sub_id] = filters

                    # Query and send stored events
                    events = await query_events(filters)
                    for ev in events:
                        await websocket.send(json.dumps(["EVENT", sub_id, ev]))
                    await websocket.send(json.dumps(["EOSE", sub_id]))

                elif msg[0] == "CLOSE":
                    sub_id = msg[1] if len(msg) > 1 else None
                    if sub_id and sub_id in SUBSCRIPTIONS.get(websocket, {}):
                        del SUBSCRIPTIONS[websocket][sub_id]
                    await websocket.send(json.dumps(["CLOSED", sub_id, ""]))

            except Exception as e:
                print(f"error handling message: {e}")
    finally:
        SUBSCRIPTIONS.pop(websocket, None)


async def process_request(connection, request):
    """Handle NIP-11 relay info requests (HTTP with Accept: application/nostr+json)."""
    accept = request.headers.get("Accept", "")
    if "application/nostr+json" in accept:
        info = {
            "name": RELAY_NAME,
            "description": RELAY_DESCRIPTION,
            "supported_nips": [1, 11],
            "software": "nostr-minimal",
            "version": "0.2.0",
        }
        if RELAY_CONTACT:
            info["contact"] = RELAY_CONTACT
        if RELAY_OWNER_PUBKEY:
            info["pubkey"] = RELAY_OWNER_PUBKEY
        body = json.dumps(info).encode()
        return Response(
            200, "OK",
            Headers([
                ("Content-Type", "application/nostr+json"),
                ("Access-Control-Allow-Origin", "*"),
            ]),
            body,
        )
    return None


async def main():
    await init_db()
    async with websockets.serve(
        handler, "0.0.0.0", 6969,
        process_request=process_request,
        ping_interval=30,
        ping_timeout=10,
        max_size=2**20,  # 1MB max message
    ):
        print(f"relay running on ws://0.0.0.0:6969")
        if RELAY_OWNER_PUBKEY:
            print(f"owner restriction: {RELAY_OWNER_PUBKEY}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
