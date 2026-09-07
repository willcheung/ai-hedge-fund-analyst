#!/usr/bin/env python3
import subprocess, time

def run(cmd):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30).stdout.strip()

old_pid = "2148848"
# Give systemd/socket adapters a short settling window if cron fires during startup.
time.sleep(5)
active = run("systemctl --user is-active hermes-gateway 2>&1")
pid = run("systemctl --user show hermes-gateway -p MainPID --value 2>&1")
status = run("hermes gateway status 2>&1 | sed -n '1,80p'")
if active == "active" and pid and pid != "0" and pid != old_pid:
    print(f"✅ Hermes gateway restarted and verified healthy. Old PID {old_pid}; new PID {pid}.\n\n{status}")
elif active == "active":
    print(f"⚠️ Hermes gateway is active, but PID did not change from the pre-restart value ({pid}).\n\n{status}")
else:
    print(f"❌ Hermes gateway restart verification failed: systemd state={active!r}, PID={pid!r}.\n\n{status}")
