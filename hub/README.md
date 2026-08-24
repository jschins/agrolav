# boekhouding-hub

Always-on hub for `workspaces/` (sibling of this folder). See [`../README.md`](../README.md).

**Center folders** (`dkg`, `jl`, …) are created on disk by an admin — the hub never initializes them. The hub only creates **person packs** (and year folders) inside an existing center.

## Listen / client `SERVER_URL`

Default `HOST=0.0.0.0` `PORT=8200`. Allow inbound TCP **8200** on the host firewall when clients on other machines need the hub.

The client has **no** `client_config.json`. Point it at the hub with env `SERVER_URL` (default `http://127.0.0.1:8200`):

| Where the client runs | `SERVER_URL` |
|-----------------------|--------------|
| Same PC as the hub | `http://127.0.0.1:8200` (default) |
| Another PC on the home LAN | `http://<hub-lan-ip>:8200` |
| Another PC via [Tailscale](https://tailscale.com/) | `http://<hub-tailscale-ip>:8200` |

Start the hub on **8200** first, then the client on **8300**.

## Hub IP gate + scoped upload

Config: `workspaces/upload_acl.json` (next to `hub/`).

```json
{
  "hub_ips": ["127.0.0.1", "100.87.15.71", "100.116.99.89"],
  "grants": [
    {
      "person": "rafael_bidarra",
      "token": "token_rafael_bidarra",
      "center": "dkg"
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `hub_ips` | Full access to **all** of `:8200`. Others get 404 on `/`. `127.0.0.1` always included. Omit/`[]` = no hub-wide gate. |
| `grants` | Upload-only tokens for Excel/CSV into one person folder |

Upload UI: `http://127.0.0.1:8200/upload` (or via public proxy if you expose only `/upload`).

## Run

```powershell
cd C:\Coding\agrolav\hub
uv sync
uv run hub
```

## Onefile

```powershell
cd C:\Coding\agrolav\hub
uv sync --group build
uv run python scripts/build_onefile.py
```

## Add person

Open `http://127.0.0.1:8200/add-person?center=<center>` (or from the client **Add person** button, which uses the client's `SERVER_URL`).
