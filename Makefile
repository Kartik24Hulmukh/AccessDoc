PYTHON ?= python3
.PHONY: run test verify smoke package
run:
	$(PYTHON) -m app.main
test:
	$(PYTHON) -W error::ResourceWarning -m unittest discover -s tests -v
verify:
	$(PYTHON) scripts/verify_release.py
smoke:
	$(PYTHON) scripts/smoke.py http://127.0.0.1:8000
package: verify
	cd .. && zip -qr AccessDoc-final.zip accessdoc -x 'accessdoc/**/__pycache__/*' 'accessdoc/**/*.pyc'
