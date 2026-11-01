# DigitalOcean deployment guide

This setup keeps the Python app bound to `127.0.0.1:8765`. Caddy provides HTTPS and a login prompt before forwarding browser requests to it. The systemd unit starts the app at boot and restarts it after an unexpected exit. No Delta credentials are placed in these deployment files; enter them in the app after connecting.

## Requirements

- Ubuntu 22.04 or 24.04 Droplet with a public IPv4 address.
- A domain or subdomain whose DNS A record points to that address. Caddy uses it to obtain and renew HTTPS certificates.
- SSH access and Python 3.10 or newer. The app uses only Python built-in libraries; no pip packages are required.

## Install Python and Caddy

On the Droplet, install Python and Caddy using the current official Caddy instructions for Ubuntu. Confirm `python3 --version` is 3.10 or newer and `caddy version` works. Do not expose port 8765 in the cloud firewall.

## Copy and install the app

Copy the project files to `/opt/delta-option-desk`, then create the dedicated service account and set ownership:

```sh
sudo useradd --system --home /opt/delta-option-desk --shell /usr/sbin/nologin deltaapp
sudo chown -R deltaapp:deltaapp /opt/delta-option-desk
sudo install -m 0644 /opt/delta-option-desk/deploy/delta-option-desk.service /etc/systemd/system/delta-option-desk.service
sudo systemctl daemon-reload
sudo systemctl enable --now delta-option-desk
sudo systemctl status delta-option-desk
```

If the service account already exists, do not create it again. If the project is copied under a different path, update `WorkingDirectory` and `ExecStart` in the installed service file first.

## Set the HTTPS login

1. Copy `deploy/Caddyfile.example` to `/etc/caddy/Caddyfile`.
2. Replace `CHANGE_ME_DOMAIN` with the DNS name pointed to the Droplet.
3. Generate a password hash with `caddy hash-password`, then replace `CHANGE_ME_USERNAME` and `CHANGE_ME_CADDY_PASSWORD_HASH` with your own username and generated hash. Keep the actual password private.
4. Validate and reload Caddy:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy obtains HTTPS certificates automatically once DNS resolves to the Droplet and inbound ports 80 and 443 are allowed.

## Firewall

In the DigitalOcean Cloud Firewall, allow inbound TCP 22 only from trusted administrator IPs where practical, and TCP 80 and 443 for web access. Do not add port 8765. On Ubuntu, configure UFW without cutting off the current SSH connection:

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
sudo ufw status
```

Before enabling UFW, confirm the SSH rule matches the server's SSH port and that DigitalOcean's cloud firewall also permits your administration connection.

## Verify and operate

- Open the HTTPS domain and sign in with the Caddy username and password.
- Check app status: `sudo systemctl status delta-option-desk`.
- View app logs: `sudo journalctl -u delta-option-desk -f`.
- Restart app: `sudo systemctl restart delta-option-desk`.
- Confirm port 8765 is listening only on loopback: `ss -lntp | grep 8765` should show `127.0.0.1:8765`.
- Add the Droplet's public IPv4 to the Delta API key allowlist. Recheck it if the Droplet IP changes; a reserved/static IP is recommended.

## Local computer

These deployment files are separate from the local Windows start script and do not change how the local dashboard starts. The local process remains running until it is stopped or the computer shuts down. The Droplet will run its own separate copy after deployment.
