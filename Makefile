.PHONY: openapi codegen test

# Regenerate the committed OpenAPI specs from the FastAPI apps. The
# pytest drift tests (search/tests/test_openapi_spec.py and
# indexer/tests/test_openapi_spec.py) fail if the committed files are
# out of sync — run this whenever you touch a route or Pydantic model.
openapi:
	python3 scripts/dump_openapi.py

# Regenerate the Go API clients (tests/client/*) from the committed
# OpenAPI specs.
codegen:
	cd tests && go generate ./...

# Convenience: run every pytest tree plus the Go smoke-CLI tests.
test:
	cd common  && python3 -m pytest tests/ --tb=short
	cd search  && python3 -m pytest tests/ --tb=short
	cd indexer && python3 -m pytest tests/ --tb=short
	cd tests   && go test ./... -count=1
