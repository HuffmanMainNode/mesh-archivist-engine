PYTHON ?= python3

.PHONY: verify test clean
verify:
	$(PYTHON) meshctl.py verify ../repo-mesh-blueprint/templates/tier1-solo
	test -f meshctl.py -a -f crawl_namespaces.py -a -f gap_planner.py -a -f diode_promote.py

test:
	$(PYTHON) -m unittest discover -s tests -v

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf tests/.tmp
