#!/usr/bin/env python3
import subprocess, time
old_pid = "2702632"

def run(cmd):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45).stdout.strip()

time.sleep(5)
active = run('systemctl --user is-active hermes-gateway 2>&1')
pid = run('systemctl --user show hermes-gateway -p MainPID --value 2>&1')
status = run('hermes gateway status 2>&1 | sed -n "1,100p"')
reason = run("python3 - <<'INNER'\nfrom hermes_cli.config import load_config\nfrom hermes_constants import resolve_reasoning_config\ncfg=load_config()\nprint('gpt-5.5 reasoning:', resolve_reasoning_config(cfg, 'gpt-5.5'))\nprint('gemini flash reasoning:', resolve_reasoning_config(cfg, 'gemini-3.1-flash-lite'))\nprint('show_reasoning:', cfg.get('display',{}).get('show_reasoning'))\nINNER")
if active == 'active' and pid and pid != '0' and pid != old_pid:
    print(f'✅ Gateway restarted and picked up reasoning settings. Old PID {old_pid}; new PID {pid}.\n\n{reason}\n\n{status}')
elif active == 'active':
    print(f'⚠️ Gateway is active, but PID did not change from pre-restart value ({pid}). Reasoning config on disk is:\n{reason}\n\n{status}')
else:
    print(f'❌ Gateway restart verification failed: state={active!r}, PID={pid!r}.\n\n{reason}\n\n{status}')
