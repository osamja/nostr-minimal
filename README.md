# Minimal Nostr Client and Relay

A simple implementation of Nostr (Notes and Other Stuff Transmitted by Relays) client and relay for testing and educational purposes.

## Prerequisites

```bash
pip install websockets secp256k1
```

## Components

**Relay (`minimal_relay.py`)**
- Listens on `ws://0.0.0.0:6969`
- Validates and stores events using ECDSA signature verification
- Handles `EVENT`, `REQ`, and `CLOSE` messages
- In-memory storage only

**Client (`minimal_client.py`)**
- Generates secp256k1 key pairs
- Creates and signs Nostr events
- Sends events via WebSocket

## Usage

Start the relay:
```bash
python minimal_relay.py
```

Send an event:
```bash
python minimal_client.py
```

## Event Structure

Events follow the Nostr specification:
- `id`: SHA-256 hash of serialized event data
- `pubkey`: 32-byte public key (hex, x-coordinate only)
- `created_at`: Unix timestamp
- `kind`: Event type (1 for text notes)
- `tags`: Array of tags (empty)
- `content`: Event content
- `sig`: ECDSA signature (compact format)

## Testing

Run the verification tests:
```bash
python test_e2e.py
```

## Limitations

- No persistence (memory-only storage)
- No filtering on REQ messages
- No real-time subscriptions
- Minimal validation beyond signature verification

## License

Educational purposes. 