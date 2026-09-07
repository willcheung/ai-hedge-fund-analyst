from automation_paths import configured_text
#!/usr/bin/env python3
import runpy
import sys
sys.argv = [configured_text('${ANALYST_HERMES_HOME}/scripts/refresh_market_dashboard.py'), '--quiet']
runpy.run_path(configured_text('${ANALYST_HERMES_HOME}/scripts/refresh_market_dashboard.py'), run_name='__main__')
