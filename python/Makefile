.PHONY: test lint fix build clean bump

test:
	uv run pytest -v

lint:
	uv run ruff check harness_common/ e2e_harness/ eval_harness/ perf_harness/ trace_harness/

fix:
	uv run ruff check --fix harness_common/ e2e_harness/ eval_harness/ perf_harness/ trace_harness/
	uv run ruff format harness_common/ e2e_harness/ eval_harness/ perf_harness/ trace_harness/

build:
	rm -rf dist
	python setup.py sdist
	cp -r dist ../dist

clean:
	rm -rf dist build *.egg-info

bump:
	@current=$$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/'); \
	major=$$(echo $$current | cut -d. -f1); \
	minor=$$(echo $$current | cut -d. -f2); \
	patch=$$(echo $$current | cut -d. -f3); \
	next="$$major.$$minor.$$((patch + 1))"; \
	sed -i '' "s/^version = \"$$current\"/version = \"$$next\"/" pyproject.toml; \
	uv lock; \
	echo "bumped $$current → $$next"
