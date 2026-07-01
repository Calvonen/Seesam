# Seesam API systemd setup

Use systemd to run the Seesam API as a background service on the host.

## Service file

Create `docs/seesam-api.service` with this content:

```ini
[Unit]
Description=Seesam API
After=network.target

[Service]
Type=simple
User=marko
WorkingDirectory=/home/marko/Seesam
EnvironmentFile=/home/marko/Seesam/.env
ExecStart=/home/marko/Seesam/.venv/bin/python -m uvicorn core.api:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## Install and start

Copy the service file into systemd, reload systemd, enable the service on boot, and start it:

```bash
sudo cp docs/seesam-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable seesam-api
sudo systemctl start seesam-api
sudo systemctl status seesam-api
```

## Manage the service

Stop the API:

```bash
sudo systemctl stop seesam-api
```

Restart the API after code or configuration changes:

```bash
sudo systemctl restart seesam-api
```

Check the current status:

```bash
sudo systemctl status seesam-api
```

Follow live logs:

```bash
sudo journalctl -u seesam-api -f
```

Show recent logs:

```bash
sudo journalctl -u seesam-api -n 100
```
