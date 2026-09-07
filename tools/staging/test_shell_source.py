"""Inspect optional operational launchers without executing any of them."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ShellBoundaryTests(unittest.TestCase):
    def test_gui_entrypoints_use_authentication_and_loopback(self):
        scripts = ROOT / 'trading-execution/scripts'
        shim = (scripts / 'start_ibkr_gui.sh').read_text()
        self.assertIn('start_ibkr_gui_service.sh', shim)
        for name in ['start_ibkr_gui.sh', 'start_ibkr_gui_service.sh', 'restart_ibkr_vnc_secure.sh']:
            text = (scripts / name).read_text()
            self.assertNotIn('-nopw', text)
            self.assertNotIn('0.0.0.0:6080', text)
            self.assertIn('ANALYST_ENABLE_LEGACY_OPS:?', text)
        for name in ['start_ibkr_gui_service.sh', 'restart_ibkr_vnc_secure.sh']:
            text = (scripts / name).read_text()
            self.assertIn('-passwdfile "$PASS_FILE"', text)
            self.assertIn('umask 077', text)
            self.assertIn('chmod 600 "$PASS_FILE"', text)

    def test_handoff_paths_are_data_not_embedded_python(self):
        text = (ROOT / 'trading-execution/scripts/prepare_ibkr_login_handoff.sh').read_text()
        self.assertIn('"$TUNNEL_PID_FILE" "$HANDOFF_JSON" "$NOVNC_LOCAL_URL" <<\'PY\'', text)
        self.assertNotIn('open("$HANDOFF_JSON"', text)
        self.assertNotIn('<<PY', text)
        self.assertGreater(text.index('mkdir -p "$STATE_DIR"'), text.index('echo "dry_run: ok"'))

    def test_evaluator_failure_is_not_reported_as_success(self):
        text = (ROOT / 'trading-execution/scripts/start_mes_signal_e2e_15s.sh').read_text()
        self.assertIn('|| rc=$?', text)
        self.assertIn('"$rc" -ne 0', text)
        self.assertNotIn('2>&1 || true', text)


if __name__ == '__main__':
    unittest.main()
