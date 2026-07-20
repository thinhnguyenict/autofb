.PHONY: bootstrap check compile screenshot smoke test whitespace worker-once

PYTHON ?= python3
AUTOFB_DASHBOARD_URL ?= http://127.0.0.1:8001

bootstrap:
	$(PYTHON) tools/bootstrap_dev_tools.py

test:
	$(PYTHON) -m unittest discover -s tests -v

compile:
	$(PYTHON) -m compileall -q autofb tests tools

whitespace:
	git diff --check

smoke:
	$(PYTHON) tools/fastapi_smoke.py

screenshot:
	AUTOFB_DASHBOARD_URL="$(AUTOFB_DASHBOARD_URL)" $(PYTHON) tools/capture_dashboard.py

worker-once:
	$(PYTHON) -c 'from autofb.web.database import Database; from autofb.web.worker import PublishWorker; import os; PublishWorker(Database(os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))).run_once()'

check: test compile whitespace smoke
