.PHONY: openapi codegen test

# Regenerate the committed OpenAPI specs from the FastAPI apps. The
# pytest drift tests (search/tests/test_openapi_spec.py and
# indexer/tests/test_openapi_spec.py) fail if the committed files are
# out of sync — run this whenever you touch a route or Pydantic model.
openapi:
	python3 scripts/dump_openapi.py

# Regenerate the Go API clients from the committed OpenAPI specs.
codegen:
	go generate ./...

# Convenience: run every pytest tree.
test:
	cd common  && python3 -m pytest tests/ --tb=short
	cd search  && python3 -m pytest tests/ --tb=short
	cd indexer && python3 -m pytest tests/ --tb=short
