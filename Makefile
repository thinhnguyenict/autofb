.PHONY: backup-db backup-offsite bootstrap check cleanup-db compile create-admin import-excel migrate-media-s3 pilot-acceptance preflight restore-db restore-drill rotate-token-key screenshot smoke test whitespace worker-once

PYTHON ?= python3
AUTOFB_DASHBOARD_URL ?= http://127.0.0.1:8001

bootstrap:
	$(PYTHON) tools/bootstrap_dev_tools.py

cleanup-db:
	$(PYTHON) tools/cleanup_database.py $(if $(DRY_RUN),--dry-run,)

backup-db:
	$(PYTHON) tools/backup_database.py

backup-offsite:
	$(PYTHON) tools/offsite_backup.py

create-admin:
	$(PYTHON) tools/create_admin.py

import-excel:
	@test -n "$(FILE)" || (echo "Usage: make import-excel FILE=data.xlsx ACTOR_EMAIL=admin@example.com WORKSPACE='Default workspace' [DRY_RUN=1]"; exit 2)
	AUTOFB_IMPORT_ACTOR_EMAIL="$(ACTOR_EMAIL)" AUTOFB_IMPORT_WORKSPACE="$(WORKSPACE)" $(PYTHON) tools/import_excel.py "$(FILE)" $(if $(DRY_RUN),--dry-run,)

migrate-media-s3:
	$(PYTHON) tools/migrate_media_to_s3.py $(if $(DRY_RUN),--dry-run,) $(if $(DELETE_LOCAL),--delete-local,)

pilot-acceptance:
	$(PYTHON) tools/pilot_acceptance.py $(if $(URL),--url "$(URL)",)

preflight:
	$(PYTHON) tools/production_preflight.py

restore-db:
	@test -n "$(BACKUP)" || (echo "Usage: make restore-db BACKUP=backups/autofb-....db [FORCE=1]"; exit 2)
	$(PYTHON) tools/restore_database.py "$(BACKUP)" $(if $(FORCE),--force,)

restore-drill:
	@test -n "$(BACKUP)" || (echo "Usage: make restore-drill BACKUP=backups/autofb-....db"; exit 2)
	$(PYTHON) tools/restore_drill.py "$(BACKUP)"

rotate-token-key:
	$(PYTHON) tools/rotate_token_key.py

test:
	$(PYTHON) -m unittest discover -s tests -v

compile:
	$(PYTHON) -m compileall -q autofb tests tools
	bash -n deploy/aapanel_ubuntu_24_04.sh deploy/install_ubuntu_24_04.sh docker-entrypoint.sh token_gen.sh

whitespace:
	git diff --check

smoke:
	$(PYTHON) tools/fastapi_smoke.py

screenshot:
	AUTOFB_DASHBOARD_URL="$(AUTOFB_DASHBOARD_URL)" $(PYTHON) tools/capture_dashboard.py

worker-once:
	$(PYTHON) -c 'from autofb.web.database import Database; from autofb.web.worker import PublishWorker; import os; PublishWorker(Database(os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))).run_once()'

check: test compile whitespace smoke
