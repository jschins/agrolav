# Deploy everything on your VPS (Ubuntu 24)

Hub, client, and `workspaces/` all run on the VPS. Caddy is the only public process.

```text
Browser → https://boekhouding.agrolav.nl
       → Caddy
       → 127.0.0.1:8300  client
       → 127.0.0.1:8200  hub  (localhost only)
```

`workspaces/` (bank data, PEMs, `users.db`) lives on the VPS disk. It is not in git. Copy it once with SCP.

Replace `<PUBLIC_IP>` with the VPS address. SSH user is `ubuntu` unless you created another.

---

## 1. Firewall and DNS

Open **22**, **80**, **443**. Do not open 8200 or 8300.

DNS: `boekhouding.agrolav.nl` → `<PUBLIC_IP>`.

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@<PUBLIC_IP>
```

---



## 2. Packages (once)

```bash
sudo apt update
sudo apt install -y git curl build-essential python3.12 python3.12-venv unzip
sudo snap install node --classic

curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"

sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

---



## 3. Code and data (once)

On the VPS:

```bash
sudo mkdir -p /opt/agrolav
sudo chown ubuntu:ubuntu /opt/agrolav
cd /opt
git clone git@github.com:jschins/agrolav.git agrolav
```

(Use `https://github.com/jschins/agrolav.git` if you have no SSH key on the VPS.)

On the **home PC**, copy data (PowerShell):

```powershell
scp -i $env:USERPROFILE\.ssh\lightsail.pem -r C:\Coding\agrolav\workspaces ubuntu@<PUBLIC_IP>:/opt/agrolav/workspaces
```

On the VPS, install and build:

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /opt/agrolav/shared && uv sync
cd /opt/agrolav/hub && uv sync
cd /opt/agrolav/client && uv sync
cd /opt/agrolav/client/frontend && npm ci && npm run build
```

---



## 4. Env and systemd (once)

```bash
sudo mkdir -p /etc/agrolav
UV=$(which uv)

sudo tee /etc/agrolav/hub.env >/dev/null <<'EOF'
HOST=127.0.0.1
PORT=8200
BOEKHOUDING_DATA_ROOT=/opt/agrolav/workspaces
EOF
sudo chmod 600 /etc/agrolav/hub.env

sudo tee /etc/agrolav/client.env >/dev/null <<'EOF'
HOST=127.0.0.1
PORT=8300
SERVER_URL=http://127.0.0.1:8200
CLIENT_AUTH=true
CLIENT_SESSION_SECRET=replace-with-a-long-random-string
CENTRALE_SYNC=true
EOF
sudo chmod 600 /etc/agrolav/client.env
```

Put a real secret in `CLIENT_SESSION_SECRET`.

```bash
sudo tee /etc/systemd/system/agrolav-hub.service >/dev/null <<EOF
[Unit]
Description=agrolav hub
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/agrolav/hub
EnvironmentFile=/etc/agrolav/hub.env
Environment=PATH=/home/ubuntu/.local/bin:/usr/bin
ExecStart=${UV} run hub
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/agrolav-client.service >/dev/null <<EOF
[Unit]
Description=agrolav client
After=network.target agrolav-hub.service
Requires=agrolav-hub.service

[Service]
User=ubuntu
WorkingDirectory=/opt/agrolav/client
EnvironmentFile=/etc/agrolav/client.env
Environment=PATH=/home/ubuntu/.local/bin:/usr/bin
ExecStart=${UV} run client
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now agrolav-hub agrolav-client
sudo systemctl status agrolav-hub agrolav-client --no-pager
```

---



## 5. Caddy (once)

```bash
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
boekhouding.agrolav.nl {
    encode gzip
    handle /api/consent/callback* {
        reverse_proxy 127.0.0.1:8200
    }
    handle /upload* {
        reverse_proxy 127.0.0.1:8200
    }
    reverse_proxy 127.0.0.1:8300
}
EOF
sudo systemctl reload caddy
```

Site: `https://boekhouding.agrolav.nl`  
Upload UI: `https://boekhouding.agrolav.nl/upload`

---



## 6. After you change code

From the home PC, push to GitHub, then on the VPS:

```bash
# Vanuit Windows
ssh agrolav@209.38.39.105 -p 4523
!ziQkpk3epcgpi70i4HvzeFa7hGukCbYi

# OPTIONEEL, want is toegevoegd aan .bashrc export PATH="$HOME/.local/bin:$PATH"
#cd /opt/agrolav
git pull
cd shared && uv sync && cd ../hub && uv sync && cd ../client && uv sync
cd /opt/agrolav/client/frontend && npm ci && npm run build
sudo systemctl restart agrolav-hub agrolav-client
```

Do not `git pull` over `workspaces/`. To refresh bank data from the PC:

```powershell
scp -i $env:USERPROFILE\.ssh\lightsail.pem -r C:\Coding\agrolav\workspaces ubuntu@<PUBLIC_IP>:/opt/agrolav/workspaces
```

Then `sudo systemctl restart agrolav-hub`.

---



## 7. Check

```bash
curl -sS http://127.0.0.1:8200/api/health
curl -sS http://127.0.0.1:8300/api/health
curl -I https://boekhouding.agrolav.nl
sudo journalctl -u agrolav-hub -u agrolav-client -e -n 50
```

Browser: `https://boekhouding.agrolav.nl`