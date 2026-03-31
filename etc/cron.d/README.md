# Automated Scheduling with Cron

The project includes a cron file (`etc/cron.d/bitcoin-node-watchdog`) that sends a heartbeat to AWS every hour.

## Installation steps

### 1. Set the repo path

Update the `HOME` variable at the top of `bitcoin-node-watchdog` to match where you cloned the repo.

### 2. Copy the scheduling file
```bash
sudo cp etc/cron.d/bitcoin-node-watchdog /etc/cron.d/
```

### 3. Set proper permissions
```bash
sudo chmod 644 /etc/cron.d/bitcoin-node-watchdog
sudo chown root:root /etc/cron.d/bitcoin-node-watchdog
```

### 4. Create the log file
The cron job runs as user `pi` which cannot create files in `/var/log/` by default:
```bash
sudo touch /var/log/bitcoin-node-watchdog-cron.log
sudo chown pi:pi /var/log/bitcoin-node-watchdog-cron.log
```

### 5. Verify cron picked it up
```bash
sudo systemctl status cron
```

## Logs

Output is appended to `/var/log/bitcoin-node-watchdog-cron.log`:
```bash
tail -f /var/log/bitcoin-node-watchdog-cron.log
```
