# SEESTAR HARDWARE PROTOCOL

Objective: Current protocol doctrine for SeeVar hardware control and acquisition.

Version: 4.1.0

## Primary Control Doctrine

SeeVar now treats Alpaca as the primary control path.

Primary protocol:
- Alpaca HTTP on port `32323`

Supporting paths:
- Alpaca discovery on UDP `32227`
- any legacy TCP/event-stream behavior is secondary and should not be treated as the canonical control interface for new work

## Port Architecture

| Port | Protocol | Purpose |
|------|----------|---------|
| `32323` | HTTP Alpaca (ASCOM) | Primary hardware control |
| `32227` | UDP broadcast | Alpaca discovery |
| `4700` | legacy / event-stream context only | Not the primary control doctrine |
| `4801` | binary stream | frame/event stream where applicable |

## Contributor Rule

New hardware-control code should target Alpaca-native behavior first.

Do not reintroduce the old assumption that “SeeVar control = TCP 4700 JSON-RPC”.

