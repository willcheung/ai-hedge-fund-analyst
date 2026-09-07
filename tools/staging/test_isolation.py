"""Exercise the real Linux isolation boundary with benign synthetic canaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

class IsolationTests(unittest.TestCase):
    def test_host_files_processes_env_and_startup_are_not_exposed(self):
        with tempfile.TemporaryDirectory(prefix='staging-canary-') as name:
            outer=Path(name)
            stage=outer/'checkout';stage.mkdir()
            secret=outer/'host-only';secret.write_text('synthetic fixture, not a credential')
            startup=outer/'startup.sh';sentinel=outer/'startup-ran'
            startup.write_text('touch '+str(sentinel)+'\n')
            host_pid=os.getpid()
            code=(
                'import pathlib,os,socket; '
                f'assert not pathlib.Path({str(secret)!r}).exists(); '
                f'assert not pathlib.Path("/proc/{host_pid}").exists(); '
                'assert not list(pathlib.Path("/root").iterdir()); '
                'assert not list(pathlib.Path("/run").iterdir()); '
                'assert set(os.environ).isdisjoint({"BASH_ENV","FAKE_SECRET_CANARY"}); '
                'assert socket.if_nameindex()==[(1,"lo")]; print("isolation passed")'
            )
            wrapper=Path(__file__).with_name('offline.sh').resolve()
            env={**os.environ,'BASH_ENV':str(startup),'FAKE_SECRET_CANARY':'synthetic'}
            result=subprocess.run(['/usr/bin/env','-i','PATH=/usr/bin:/bin',
                'STAGING_ROOT='+str(stage),'/bin/bash',str(wrapper),'/usr/bin/python3','-c',code],
                cwd=stage,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('isolation passed',result.stdout)
            self.assertFalse(sentinel.exists())

if __name__=='__main__':unittest.main()
