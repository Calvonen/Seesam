# Seesam API systemd setup

Seesam API runs on this host as the system-level systemd service `seesam-api.service`.
The installed unit is `/etc/systemd/system/seesam-api.service`, and the repository copy is `docs/seesam-api.service`.

The service starts uvicorn with:

```sh
/home/marko/Seesam/.venv/bin/python -m uvicorn core.api:app --host 0.0.0.0 --port 8000
```

Because the unit uses `Restart=always`, killing the uvicorn process directly makes systemd start it again after `RestartSec=5`. Stop, start, and restart it with `systemctl` instead.

## Service file

`docs/seesam-api.service` contains the canonical unit:

```ini
[Unit]
Description=Seesam API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=marko
WorkingDirectory=/home/marko/Seesam
EnvironmentFile=/home/marko/Seesam/.env
ExecStart=/home/marko/Seesam/.venv/bin/python -m uvicorn core.api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Install or update the service

Copy the repository unit into systemd, reload systemd, enable boot startup, and start the service:

```bash
sudo cp docs/seesam-api.service /etc/systemd/system/seesam-api.service
sudo systemctl daemon-reload
sudo systemctl enable seesam-api
sudo systemctl start seesam-api
systemctl status seesam-api --no-pager
```

After changing `docs/seesam-api.service`, run the copy and `daemon-reload` commands again before restarting.

## Manage the service

Stop the API:

```bash
sudo systemctl stop seesam-api
```

Start the API:

```bash
sudo systemctl start seesam-api
```

Restart the API after code or configuration changes:

```bash
sudo systemctl restart seesam-api
```

Check the current status:

```bash
systemctl status seesam-api --no-pager
```

Follow live logs:

```bash
journalctl -u seesam-api -f
```

Show recent logs:

```bash
journalctl -u seesam-api -n 100 --no-pager
```
