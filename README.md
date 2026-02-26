# Minimal Nostr Client and Relay

A minimal personal Nostr relay and client. SQLite persistence, NIP-01 filters, live subscriptions, NIP-11 relay info, and optional owner-only publishing.

## Prerequisites

```bash
pip install websockets secp256k1 aiosqlite
```

## Components

**Relay (`minimal_relay.py`)**
- Listens on `ws://0.0.0.0:6969`
- SQLite persistence with WAL mode
- ECDSA signature verification
- NIP-01 filter matching (`ids`, `authors`, `kinds`, `since`, `until`, `#<tag>`)
- Live subscriptions with `EVENT`/`EOSE`/`CLOSED` responses
- NIP-11 relay information document
- Optional owner-only publishing restriction

**Client (`minimal_client.py`)**
- Generates secp256k1 key pairs
- Creates and signs Nostr events
- Sends events via WebSocket

## Usage

Start the relay:
```bash
python minimal_relay.py
```

With Docker:
```bash
docker build -t nostr-minimal .
docker run -p 6969:6969 nostr-minimal
```

Send an event:
```bash
python minimal_client.py
```

## Configuration

All config is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `RELAY_DB_PATH` | `relay.db` | SQLite database path |
| `RELAY_OWNER_PUBKEY` | (empty) | Restrict publishing to this pubkey |
| `RELAY_NAME` | `nostr-minimal` | Relay name (NIP-11) |
| `RELAY_DESCRIPTION` | `A minimal personal Nostr relay` | Relay description (NIP-11) |
| `RELAY_CONTACT` | (empty) | Contact info (NIP-11) |

## Testing

Run the verification tests:
```bash
python test_e2e.py
```

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.