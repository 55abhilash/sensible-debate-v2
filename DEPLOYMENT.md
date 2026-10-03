# Deploying Sensible Debate to an Ubuntu server

This walks through putting the app on a plain Ubuntu VPS - the kind of
box Hostinger, GoDaddy, DigitalOcean, or almost any other host will sell
you as "Ubuntu 22.04" or "Ubuntu 24.04". Nothing here is Hostinger-specific
except step 1 (where you get the server) - the rest is the same on any
Ubuntu VPS.

This single-server setup is the simpler, cheaper option. If you expect
enough traffic to need more than one server with automatic scaling,
see `DEPLOYMENT_AWS.md` instead - same app, deployed across multiple
instances behind a load balancer with shared state via Redis.

Read **"A word about WebSockets"** near the end before you go live - it's
the one part of this stack that's easy to get subtly wrong.

## What you'll end up with

```
Browser  →  nginx (port 80/443, handles HTTPS)  →  uvicorn (port 8000, one process)  →  SQLite file + local Redis
```

nginx is a reverse proxy sitting in front of the app: it terminates
HTTPS, forwards regular requests and WebSocket connections to the Python
process, and is what actually faces the internet. uvicorn (running your
FastAPI app) only ever listens on `127.0.0.1`, never on the public
interface.

---

## 1. Get a server and point your domain at it

1. In Hostinger (or GoDaddy, etc.), order a VPS plan and pick **Ubuntu
   22.04** or **24.04** as the OS image. You'll be given a public IP
   address and root (or sudo) SSH access - usually emailed to you, or
   shown in the hosting panel.
2. In your domain's DNS settings (also in the Hostinger/GoDaddy panel,
   under something like "DNS Zone" or "DNS Management"), add:
   - An **A record** for `@` (or your domain root) pointing at the
     server's IP address.
   - An **A record** for `www` pointing at the same IP, if you want
     `www.yourdomain.com` to work too.

   DNS changes can take anywhere from a few minutes to a few hours to
   spread. You can move on to the next steps while you wait.

## 2. First login and basic server setup

SSH in as the user the host gave you (often `root`):

```bash
ssh root@YOUR_SERVER_IP
```

Update the system and create a normal (non-root) user to run things as -
running your app as root is unnecessary risk:

```bash
apt update && apt upgrade -y
adduser deploy
usermod -aG sudo deploy
```

Follow the prompts to set a password for `deploy`, then switch to it for
everything else:

```bash
su - deploy
```

Turn on a basic firewall, allowing only SSH and web traffic:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'   # allows both port 80 and 443
sudo ufw enable
```

## 3. Install system dependencies

```bash
sudo apt install -y python3 python3-venv python3-pip nginx git redis-server
```

Ubuntu's `redis-server` package starts and enables itself automatically
on install, bound to `127.0.0.1` by default - which is exactly right
here. Redis holds the *live* state of debates in progress (whose turn
it is, timers, messages not yet finished) and is a required dependency
now, not an optional cache - confirm it's running before moving on:

```bash
redis-cli ping   # should print PONG
```

## 4. Get the code onto the server

Whichever of these is easiest for you:

**Option A - upload the project as a zip** (simplest if you're not using
git):

```bash
# from your own machine, not the server:
scp sensible-debate.zip deploy@YOUR_SERVER_IP:~

# back on the server:
sudo apt install -y unzip
unzip sensible-debate.zip -d ~/sensible-debate
```

**Option B - clone from a git repository**, if you've pushed this
project somewhere like GitHub:

```bash
git clone YOUR_REPOSITORY_URL ~/sensible-debate
```

Either way, you should now have `~/sensible-debate` on the server with
the same folder structure described in `README.md`.

## 5. Create the virtual environment and install dependencies

```bash
cd ~/sensible-debate
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Configure the app

```bash
cp .env.example .env
nano .env
```

The defaults (5-minute arguments, 2-minute reflection) match the spec
this app was built around - you probably don't need to change anything
here except maybe `SD_MAX_ROUNDS` if you want debates to automatically
end after a fixed number of rounds. Save and exit (`Ctrl+O`, `Enter`,
`Ctrl+X` in nano).

## 7. Test it manually before wiring up nginx

```bash
source venv/bin/activate   # if not already active
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From a second terminal on the same server:

```bash
curl -I http://127.0.0.1:8000/
```

You should see `HTTP/1.1 200 OK`. Stop the test server with `Ctrl+C` once
you've confirmed that - the next step runs it properly, as a background
service.

## 8. Run it as a systemd service

This makes the app start on boot and restart automatically if it ever
crashes. Create the service file:

```bash
sudo nano /etc/systemd/system/sensible-debate.service
```

Paste this in, adjusting the paths only if you put the project somewhere
other than `/home/deploy/sensible-debate`:

```ini
[Unit]
Description=Sensible Debate
After=network.target redis-server.service

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/sensible-debate
EnvironmentFile=/home/deploy/sensible-debate/.env
ExecStart=/home/deploy/sensible-debate/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Live debate state now lives in Redis rather than in-process (this is
also what makes the AWS multi-instance version in `DEPLOYMENT_AWS.md`
possible), so unlike earlier versions of this guide, running more than
one `uvicorn` worker here is actually safe if this VPS has more than
one vCPU to spare - add `--workers 2` to `ExecStart` for a 2-vCPU box.
It's just not necessary: a single worker comfortably handles far more
concurrent debates than a small VPS's network connection will see in
practice, so leave it at one unless you have a specific reason not to.

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sensible-debate
sudo systemctl start sensible-debate
sudo systemctl status sensible-debate
```

`status` should show `active (running)`. If it doesn't, check the logs:

```bash
sudo journalctl -u sensible-debate -f
```

## 9. Configure nginx as a reverse proxy

Create a site config:

```bash
sudo nano /etc/nginx/sites-available/sensible-debate
```

```nginx
# Required once per nginx install to let WebSocket upgrade headers through.
# If another site config on this server already defines this exact map
# block, don't repeat it - nginx will refuse to reload with a duplicate.
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # WebSocket upgrade support - required, see the note below.
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # A debate turn can sit open and silent for several minutes at a
        # time - see "A word about WebSockets" below for why this matters.
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Replace `yourdomain.com` with your actual domain in both places. Enable
the site and check the config is valid before reloading:

```bash
sudo ln -s /etc/nginx/sites-available/sensible-debate /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

At this point, `http://yourdomain.com` should load the site over plain
HTTP. Confirm that before moving on to HTTPS.

## 10. Add HTTPS with Let's Encrypt (free, and you should do this)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Certbot will ask for an email (for renewal notices) and offer to
redirect all HTTP traffic to HTTPS - say yes. It edits the nginx config
you just wrote to add the certificate and the redirect automatically.

Certbot also installs a systemd timer that renews the certificate
automatically before it expires. You can confirm that's working with:

```bash
sudo certbot renew --dry-run
```

Your site is now live at `https://yourdomain.com`.

---

## A word about WebSockets (read this)

This app's core feature - the live back-and-forth debate - runs over a
single long-lived WebSocket connection per person, not repeated HTTP
requests. Two things about that are easy to get wrong when a reverse
proxy sits in front of it, and both are already handled in the nginx
config above, but it's worth understanding *why*:

1. **The `Upgrade`/`Connection` headers.** A WebSocket starts life as a
   normal HTTP request that asks to be "upgraded" to a different
   protocol. If a proxy doesn't forward that upgrade request correctly,
   the connection fails immediately (usually as a `400` or `502` in the
   browser's network tab). The `map` block and the two `proxy_set_header`
   lines above are what make that work.
2. **Idle timeouts.** During a 5-minute argument turn, the connection can
   sit with zero bytes flowing over it if the app has nothing new to say
   and you haven't sent anything yet. nginx's *default* read timeout is
   only 60 seconds - without raising it, nginx would silently kill the
   connection partway through nearly every single turn, which would look
   like "the app randomly disconnects me while I'm writing." The
   `proxy_read_timeout 3600s;` / `proxy_send_timeout 3600s;` lines fix
   this. (In practice, uvicorn also sends its own low-level keep-alive
   pings roughly every 20 seconds, which would likely paper over the
   default timeout most of the time anyway - but don't rely on that;
   set the explicit timeout.)

If you ever see debates disconnecting after almost exactly 60 seconds of
silence, this is the first thing to check.

## Day-to-day operations

**View live logs:**
```bash
sudo journalctl -u sensible-debate -f
```

**Restart after a config or code change:**
```bash
sudo systemctl restart sensible-debate
```

**Deploy a code update:**
```bash
cd ~/sensible-debate
git pull                              # or re-upload and unzip, if not using git
source venv/bin/activate
pip install -r requirements.txt       # only needed if requirements.txt changed
sudo systemctl restart sensible-debate
```

**Back up the database.** It's a single SQLite file - back it up like
any other file:
```bash
cp ~/sensible-debate/data/sensible_debate.db ~/backups/sensible_debate-$(date +%F).db
```
Consider putting that line in a daily cron job (`crontab -e`).

**Nginx error log**, if something's wrong at the proxy layer specifically:
```bash
sudo tail -f /var/log/nginx/error.log
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `502 Bad Gateway` from nginx | The app isn't running - check `sudo systemctl status sensible-debate` and the journalctl logs above. |
| WebSocket fails to connect (visible in browser dev tools → Network → WS) | Double-check the `map`/`Upgrade`/`Connection` block in the nginx config, and that you reloaded nginx (`sudo nginx -t && sudo systemctl reload nginx`) after editing it. |
| Debates disconnect after roughly a minute of silence | Missing or too-low `proxy_read_timeout` / `proxy_send_timeout` - see "A word about WebSockets" above. |
| Certbot fails with a domain validation error | Your DNS A record hasn't propagated yet, or isn't pointing at this server. Check with `dig yourdomain.com` and wait/retry. |
| Two people's debates seem to interfere with each other, or state looks wrong | Confirm Redis is actually running (`redis-cli ping`) and reachable at the `SD_REDIS_URL` in `.env` - live debate coordination depends on it now. |
