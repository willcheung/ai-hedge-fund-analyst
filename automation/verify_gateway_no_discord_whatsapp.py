from automation_paths import configured_text
#!/usr/bin/env python3
import subprocess, time, re
old_pid = "2704847"

def run(cmd, timeout=45):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout).stdout.strip()

time.sleep(5)
active = run('systemctl --user is-active hermes-gateway 2>&1')
pid = run('systemctl --user show hermes-gateway -p MainPID --value 2>&1')
status = run('hermes gateway status 2>&1 | sed -n "1,120p"')
# Check current active config/env only; do not inspect source/backups.
config_check = run(configured_text("python3 - <<'INNER'\nfrom pathlib import Path\nimport re, yaml, json\npat=re.compile(r'(discord|whatsapp|whats[ _-]?app|greenapi|green_api|baileys)', re.I)\ncfg_text=Path('${ANALYST_HERMES_HOME}/config.yaml').read_text()\nenv_text=Path('${ANALYST_HERMES_HOME}/.env').read_text(errors='ignore') if Path('${ANALYST_HERMES_HOME}/.env').exists() else ''\ncfg=yaml.safe_load(cfg_text) or {}\nprint(json.dumps({\n  'active_config_match_count': sum(1 for _ in pat.finditer(cfg_text)),\n  'active_env_match_count': sum(1 for _ in pat.finditer(env_text)),\n  'platforms': sorted((cfg.get('platforms') or {}).keys()) if isinstance(cfg.get('platforms'), dict) else [],\n  'platform_toolsets_has_discord': 'discord' in (cfg.get('platform_toolsets') or {}),\n  'platform_toolsets_has_whatsapp': 'whatsapp' in (cfg.get('platform_toolsets') or {}),\n}))\nINNER"))
# Look only at recent gateway log tail after restart; report counts/snippets without secrets.
log_tail = run(configured_text("tail -n 250 ${ANALYST_HERMES_HOME}/logs/gateway.log 2>/dev/null | grep -Ei 'discord|whatsapp|greenapi|baileys|error|failed|exception' | tail -n 40 || true"))
platform_noise = [ln for ln in log_tail.splitlines() if re.search(r'discord|whatsapp|greenapi|baileys', ln, re.I)]
if active == 'active' and pid and pid != '0' and pid != old_pid and not platform_noise:
    print(f'✅ Gateway restarted cleanly with Discord/WhatsApp removed. Old PID {old_pid}; new PID {pid}.\n\nConfig check: {config_check}\n\nGateway status:\n{status}')
elif active == 'active':
    print(f'⚠️ Gateway is active after restart check. Old PID {old_pid}; current PID {pid}. Discord/WhatsApp-related recent log lines: {len(platform_noise)}\n\nConfig check: {config_check}\n\nRecent relevant log lines:\n' + ('\n'.join(platform_noise[-20:]) if platform_noise else '[none]') + f'\n\nGateway status:\n{status}')
else:
    print(f'❌ Gateway is not active after Discord/WhatsApp removal. state={active!r}, PID={pid!r}\n\nConfig check: {config_check}\n\nRecent relevant log lines:\n{log_tail}\n\nGateway status:\n{status}')
