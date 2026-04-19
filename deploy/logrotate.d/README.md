# Log rotation with logrotate

The project includes a logrotate drop-in (`bitcoin-node-watchdog`) that keeps
`/var/log/bitcoin-node-watchdog-cron.log` from growing unbounded on the Pi.

Rotation schedule:
- weekly, keeping 4 compressed copies (~one month of history)
- skipped if the log is missing or empty
- rotated file recreated as `pi:pi` (the cron user) so writes still succeed

## Installation steps

### 1. Copy the drop-in
```bash
sudo cp bitcoin-node-watchdog /etc/logrotate.d/
```

### 2. Set proper permissions
```bash
sudo chmod 644 /etc/logrotate.d/bitcoin-node-watchdog
sudo chown root:root /etc/logrotate.d/bitcoin-node-watchdog
```

### 3. Dry-run to verify
```bash
sudo logrotate -d /etc/logrotate.d/bitcoin-node-watchdog
```
The `-d` flag simulates rotation without touching any files — inspect the
output for errors or unexpected actions before relying on it.

### 4. Force a first rotation (optional)
```bash
sudo logrotate -f /etc/logrotate.d/bitcoin-node-watchdog
```
Subsequent rotations happen automatically via `/etc/cron.daily/logrotate`.
