# Deploying Scholaris for free (Oracle Cloud Always Free)

This guide puts Scholaris on a real, always-on server with its own HTTPS URL,
a persistent SQLite database, and the shared access-code gate. It costs **$0**
and has **no cold starts** (unlike free app hosts that sleep).

What you end up with:

- `https://<your-ip>.sslip.io` — one URL for the app and the API
- One shared access code (change it any time)
- Your library stored on the server's disk at `/var/lib/scholaris/library.sqlite3`
- Automatic HTTPS certificates (Caddy + Let's Encrypt)
- Automatic restart on reboot or crash (systemd)
- Per-IP rate limits on the API

The installer is [`deploy/oracle-setup.sh`](../deploy/oracle-setup.sh); updates use
[`deploy/update.sh`](../deploy/update.sh). Both are plain bash and safe to read
before running.

---

## 1. Create the free server

1. Sign up at <https://cloud.oracle.com> (a card is used for identity
   verification; Always Free resources are not charged). Pick a home region
   close to you.
2. Open **Compute → Instances → Create instance**.
3. **Name:** `scholaris`
4. **Image:** Canonical Ubuntu 24.04 (or 22.04). For an Ampere shape pick the
   aarch64 image; for the AMD micro pick the x86_64 image.
5. **Shape:**
   - **Ampere → `VM.Standard.A1.Flex`** with **1 OCPU / 6 GB** is plenty.
     Always Free covers up to 4 OCPUs / 24 GB in total.
   - If Ampere capacity is unavailable in your region, choose
     **`VM.Standard.E2.1.Micro`** (Always Free, 1 GB RAM). The frontend build is
     small enough to fit; the installer adds nothing heavy.
6. **Networking:** create a VCN with a **public subnet** (the wizard default),
   and make sure **Assign a public IPv4 address** is **Yes**.
7. **SSH keys:** choose **Generate a key pair** and download the private key
   (or upload your own public key). You need this to log in.
8. **Boot volume:** the default 50 GB is fine (Always Free includes 200 GB
   total).
9. Create the instance and wait until it is **Running**. Copy its **Public IP
   address**.

> **Keep the IP stable (recommended).** On the instance's page, open the VNIC →
> IPv4 addresses → the public IP → **Reserve** it. A reserved IP survives
> stop/start; an ephemeral one can change.

## 2. Open HTTPS ports

Oracle blocks inbound traffic in the VCN until you allow it.

1. **Networking → Virtual Cloud Networks →** your VCN **→ Security Lists →**
   the default security list.
2. **Add Ingress Rules** twice:
   - Source CIDR `0.0.0.0/0`, IP Protocol **TCP**, Destination Port **80**
   - Source CIDR `0.0.0.0/0`, IP Protocol **TCP**, Destination Port **443**

Leave port 22 open for SSH. If your subnet uses a Network Security Group,
add the same two rules there instead.

## 3. Connect to the server

From Windows PowerShell (replace the key path and IP):

```powershell
ssh -i C:\Users\you\Downloads\ssh-key-2026-10-21.key ubuntu@203.0.113.10
```

If SSH complains about key permissions, either use WSL, or restrict the key:

```powershell
icacls "C:\Users\you\Downloads\ssh-key-2026-10-21.key" /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

## 4. Install Scholaris

On the server:

```bash
sudo apt-get update
sudo apt-get install -y curl
curl -fsSL https://raw.githubusercontent.com/swll99ffx/scholaris/main/deploy/oracle-setup.sh -o oracle-setup.sh
less oracle-setup.sh          # optional: review it
sudo PUBLIC_HOST=203.0.113.10.sslip.io bash oracle-setup.sh
```

Replace `203.0.113.10` with your **public IP**. The installer:

- installs Python, Node.js and Caddy
- downloads the latest `main` branch
- builds the React app and installs the backend
- asks for the **site access code** (it is not echoed, and never goes into the
  command line)
- writes `/etc/scholaris.env` (root-only, `600`)
- runs the app as the `scholaris` systemd service behind Caddy

`sslip.io` is a free wildcard-DNS service: `<your-ip>.sslip.io` resolves to
your IP, which lets Caddy obtain a real Let's Encrypt certificate without you
buying a domain. If `sslip.io` does not resolve in your region, use
`<your-ip>.nip.io` instead.

When it finishes, open the printed URL and enter your access code.

## 5. Verify

```bash
curl -I https://203.0.113.10.sslip.io/api/health
sudo systemctl status scholaris
sudo journalctl -u scholaris -f
```

Expected health response:

```json
{"status": "ok", "app": "Scholaris", "version": "1.0.0", "ai": "free"}
```

The access code is required for every API route except `/api/health` and the
auth endpoints. Changing it signs everyone out.

## Day-to-day operations

### Update to the latest code

```bash
sudo bash /opt/scholaris/deploy/update.sh
```

This pulls `main`, reinstalls dependencies, rebuilds the frontend and restarts
the service. Your access code, library and saved notes are untouched.

### Change the access code

```bash
sudo nano /etc/scholaris.env      # edit SITE_PASSWORD
sudo systemctl restart scholaris
```

### Back up the library

```bash
sudo sqlite3 /var/lib/scholaris/library.sqlite3 \
  ".backup '/tmp/library-backup.sqlite3'"
```

Copy it to your PC with `scp` (run locally):

```powershell
scp ubuntu@203.0.113.10:/tmp/library-backup.sqlite3 .
```

To restore: stop the service, copy the backup to
`/var/lib/scholaris/library.sqlite3`, then start the service.

### Useful commands

| Task | Command |
| --- | --- |
| App logs | `sudo journalctl -u scholaris -f` |
| HTTPS/proxy logs | `sudo journalctl -u caddy -f` |
| Restart app | `sudo systemctl restart scholaris` |
| Reload proxy | `sudo systemctl reload caddy` |
| Edit config | `sudo nano /etc/scholaris.env` |

## Troubleshooting

**HTTPS never becomes ready**

1. Confirm the URL resolves: `getent hosts 203.0.113.10.sslip.io`
2. Confirm ports are open in the VCN security list (80 and 443).
3. Check Caddy: `sudo systemctl status caddy` and
   `sudo journalctl -u caddy -n 80 --no-pager`.
4. Make sure no other service is using port 80:
   `sudo ss -ltnp | grep ':80 '`.

**"Out of capacity" when creating the Ampere instance**

Retry later, try a different availability domain, or choose the AMD
`VM.Standard.E2.1.Micro` shape. Both are Always Free.

**The site loads but every action says "Access code required"**

The browser is not sending the session cookie. Confirm you are using the
`https://` URL (not a direct IP or port 8000) and that the clock on the server
is correct. Restart the app after changing `SITE_PASSWORD`.

**Oracle reclaims idle Always Free instances**

Oracle may reclaim Always Free compute that stays idle for long periods. A
personal app used regularly is normally fine. If you want belt-and-suspenders
availability, keep a copy of this repo and re-run the installer on a fresh
instance; the library backup above is the only state you need.

## Cost guardrails

- Stay on an Always Free shape; do not resize to a paid shape.
- Keep the boot volume at or below 200 GB total.
- No paid services are required: the app uses keyless scholarly APIs and the
  built-in keyless AI fallback. Optional API keys only raise provider limits.

## Alternative: run it on your own PC

If you would rather not use a cloud VM, build the frontend and run the single
process described in the README, then expose it with
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel) (`tailscale funnel 8000`).
That also costs $0 and has no cold start, but the PC must stay on.
