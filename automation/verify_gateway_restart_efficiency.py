#!/usr/bin/env python3
import subprocess, time
old_pid = "2703463"

def run(cmd):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45).stdout.strip()

time.sleep(5)
active = run('systemctl --user is-active hermes-gateway 2>&1')
pid = run('systemctl --user show hermes-gateway -p MainPID --value 2>&1')
summary = run("python3 - <<'INNER'\nfrom hermes_cli.config import load_config\ncfg=load_config()\nprint('busy_input_mode:', cfg.get('display',{}).get('busy_input_mode'))\nprint('tool_search:', cfg.get('tools',{}).get('tool_search'))\nprint('delegation:', {k: cfg.get('delegation',{}).get(k) for k in ['reasoning_effort','max_concurrent_children','max_spawn_depth','child_timeout_seconds','subagent_auto_approve']})\nprint('agent bools:', cfg.get('agent',{}).get('intent_ack_continuation'), type(cfg.get('agent',{}).get('intent_ack_continuation')).__name__, cfg.get('agent',{}).get('verify_on_stop'), type(cfg.get('agent',{}).get('verify_on_stop')).__name__)\nINNER")
status = run('hermes gateway status 2>&1 | sed -n "1,80p"')
if active == 'active' and pid and pid != '0' and pid != old_pid:
    print(f'✅ Gateway restarted after efficiency tweaks. Old PID {old_pid}; new PID {pid}.\n\n{summary}\n\n{status}')
elif active == 'active':
    print(f'⚠️ Gateway is active, but PID did not change from pre-restart value ({pid}). Config on disk is:\n{summary}\n\n{status}')
else:
    print(f'❌ Gateway restart verification failed: state={active!r}, PID={pid!r}.\n\n{summary}\n\n{status}')
