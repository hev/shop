package cmd

// HTTP roundtrip tests for the indexer-pointed commands plus the
// composite `shop health` command. Same pattern as search_test.go.

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestIndexCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"pipeline_id": "p1", "namespace": "amazon-products",
		"category": "Electronics", "count": 100, "jobs_created": 1,
	})
	if err := runArgs(t,
		"index",
		"--indexer-url", srv.URL,
		"--count", "100",
		"--category", "Electronics",
		"--job-size", "50",
	); err != nil {
		t.Fatalf("index cmd failed: %v", err)
	}
	if recorded.Method != "POST" || recorded.Path != "/index" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Body["count"].(float64) != 100 {
		t.Errorf("expected count=100, got %v", recorded.Body["count"])
	}
	if recorded.Body["category"] != "Electronics" {
		t.Errorf("expected category=Electronics, got %v", recorded.Body["category"])
	}
	if recorded.Body["job_size"].(float64) != 50 {
		t.Errorf("expected job_size=50, got %v", recorded.Body["job_size"])
	}
}

func TestStatusCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"pipeline_id": "hev-shop-product-images",
		"layer":       map[string]any{},
		"jobs":        map[string]any{},
	})
	if err := runArgs(t,
		"status",
		"--indexer-url", srv.URL,
		"--pipeline-id", "hev-shop-product-images",
	); err != nil {
		t.Fatalf("status cmd failed: %v", err)
	}
	if recorded.Method != "GET" || recorded.Path != "/status" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Query.Get("pipeline_id") != "hev-shop-product-images" {
		t.Errorf("expected pipeline_id query param, got %v", recorded.Query)
	}
}

// healthCmd hits two services, so use distinct servers and assert both
// were called.
func TestHealthCmdHitsBothServices(t *testing.T) {
	resetCLIState()
	var searchHit, indexerHit bool
	searchSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			searchHit = true
		}
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	}))
	t.Cleanup(searchSrv.Close)
	indexerSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/status" {
			indexerHit = true
		}
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"pipeline_id":"p1","layer":{},"jobs":{}}`))
	}))
	t.Cleanup(indexerSrv.Close)

	if err := runArgs(t,
		"health",
		"--search-url", searchSrv.URL,
		"--indexer-url", indexerSrv.URL,
	); err != nil {
		t.Fatalf("health cmd failed: %v", err)
	}
	if !searchHit {
		t.Error("expected search /healthz to be called")
	}
	if !indexerHit {
		t.Error("expected indexer /status to be called")
	}
}
