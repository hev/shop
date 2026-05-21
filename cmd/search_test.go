package cmd

// HTTP roundtrip tests for the search-pointed commands. Each test spins
// up an httptest.Server, points `--search-url` at it, runs the cobra
// command, and asserts the method/path/body the CLI actually sent — so
// any spec/CLI drift surfaces here without needing a live ALB.

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func resetCLIState() {
	// cobra flags persist across test invocations within a process —
	// reset the package-level globals each test so flag state from a
	// prior test doesn't leak into the next.
	apiBase = ""
	searchURL = ""
	indexerURL = ""

	searchQuery, searchTopK, searchCategory = "", 10, ""
	searchTags, searchCursor = nil, ""
	searchWithCount = false
	searchMaxDistance, searchNamespace = 0.4, ""

	recommendASIN, recommendTopK = "", 10
	recommendCategory, recommendNamespace = "", ""

	metaNamespace = ""

	reviewSearchQuery, reviewSearchASIN = "", ""
	reviewSearchTopK, reviewSearchCategory = 10, ""
	reviewSearchCursor = ""
	reviewSearchWithCount = false
	reviewSearchMaxDistance = 0.4

	reviewSamplesASIN = ""
	reviewSamplesIDs = nil

	indexCount, indexCategory = 10000, "Electronics"
	indexCategories = nil
	indexPipelineID, indexJobSize, indexNamespace = "", 10000, ""

	backfillCategory = "Electronics"
	backfillAsins, backfillStages = nil, nil
	backfillProductLimit = 1000
	backfillReviewsPerProduct, backfillMaxTotalReviews = 0, 0
	backfillPipelineID, backfillNamespace = "", ""

	statusPipelineID = ""
}

type recordedRequest struct {
	Method string
	Path   string
	Query  url.Values
	Body   map[string]any
}

func recordingServer(t *testing.T, respStatus int, respBody any) (*httptest.Server, *recordedRequest) {
	t.Helper()
	recorded := &recordedRequest{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		recorded.Method = r.Method
		recorded.Path = r.URL.Path
		recorded.Query = r.URL.Query()
		raw, _ := io.ReadAll(r.Body)
		if len(raw) > 0 {
			_ = json.Unmarshal(raw, &recorded.Body)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(respStatus)
		_ = json.NewEncoder(w).Encode(respBody)
	}))
	t.Cleanup(srv.Close)
	return srv, recorded
}

func runArgs(t *testing.T, args ...string) error {
	t.Helper()
	rootCmd.SetArgs(args)
	rootCmd.SetOut(io.Discard)
	rootCmd.SetErr(io.Discard)
	return rootCmd.Execute()
}

func TestSearchCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"query":     "headphones",
		"namespace": "amazon-products",
		"hits":      []any{},
	})

	if err := runArgs(t,
		"search", "headphones",
		"--search-url", srv.URL,
		"--top-k", "3",
		"--category", "Electronics",
		"--tags", "Overpriced,Stylish",
	); err != nil {
		t.Fatalf("search cmd failed: %v", err)
	}
	if recorded.Method != "POST" || recorded.Path != "/search" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Body["query"] != "headphones" {
		t.Errorf("expected query=headphones, got %v", recorded.Body["query"])
	}
	if recorded.Body["top_k"].(float64) != 3 {
		t.Errorf("expected top_k=3, got %v", recorded.Body["top_k"])
	}
	if recorded.Body["category"] != "Electronics" {
		t.Errorf("expected category=Electronics, got %v", recorded.Body["category"])
	}
	tags, ok := recorded.Body["tags"].([]any)
	if !ok || len(tags) != 2 {
		t.Fatalf("expected 2 tags, got %v", recorded.Body["tags"])
	}
}

func TestRecommendCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"asin":      "B0001",
		"namespace": "amazon-products",
		"hits":      []any{},
	})
	if err := runArgs(t,
		"recommend", "B0001",
		"--search-url", srv.URL,
		"--top-k", "5",
		"--category", "Electronics",
	); err != nil {
		t.Fatalf("recommend cmd failed: %v", err)
	}
	if recorded.Method != "POST" || recorded.Path != "/recommend" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Body["asin"] != "B0001" {
		t.Errorf("expected asin=B0001, got %v", recorded.Body["asin"])
	}
	if recorded.Body["top_k"].(float64) != 5 {
		t.Errorf("expected top_k=5, got %v", recorded.Body["top_k"])
	}
}

func TestRecommendCmdMissingASIN(t *testing.T) {
	resetCLIState()
	srv, _ := recordingServer(t, 200, map[string]any{})
	err := runArgs(t, "recommend", "--search-url", srv.URL)
	if err == nil || !strings.Contains(err.Error(), "seed ASIN is required") {
		t.Fatalf("expected ASIN-required error, got: %v", err)
	}
}

func TestProductCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"asin": "B00FI7TCGI", "namespace": "amazon-products", "attributes": map[string]any{},
	})
	if err := runArgs(t, "product", "B00FI7TCGI", "--search-url", srv.URL); err != nil {
		t.Fatalf("product cmd failed: %v", err)
	}
	if recorded.Method != "GET" || recorded.Path != "/product/B00FI7TCGI" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
}

func TestMetaCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"namespace": "amazon-products", "vectors": 0, "categories": []any{},
	})
	if err := runArgs(t, "meta", "--search-url", srv.URL, "--namespace", "amazon-products"); err != nil {
		t.Fatalf("meta cmd failed: %v", err)
	}
	if recorded.Method != "GET" || recorded.Path != "/meta" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Query.Get("namespace") != "amazon-products" {
		t.Errorf("expected namespace query param, got %v", recorded.Query)
	}
}

func TestSearchReviewsCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"query": "battery", "namespace": "rev", "asin": "B0001", "hits": []any{},
	})
	if err := runArgs(t,
		"search-reviews",
		"--search-url", srv.URL,
		"--query", "battery",
		"--asin", "B00FI7TCGI",
		"--top-k", "4",
	); err != nil {
		t.Fatalf("search-reviews cmd failed: %v", err)
	}
	if recorded.Method != "GET" || recorded.Path != "/search/reviews" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Query.Get("asin") != "B00FI7TCGI" || recorded.Query.Get("q") != "battery" {
		t.Errorf("unexpected query: %v", recorded.Query)
	}
	if recorded.Query.Get("top_k") != "4" {
		t.Errorf("expected top_k=4, got %v", recorded.Query.Get("top_k"))
	}
}

func TestReviewSamplesCmdSendsRequest(t *testing.T) {
	resetCLIState()
	srv, recorded := recordingServer(t, 200, map[string]any{
		"asin": "B0001", "samples": []any{},
	})
	if err := runArgs(t,
		"review-samples",
		"--search-url", srv.URL,
		"--asin", "B0001",
		"--ids", "r1,r2,r3",
	); err != nil {
		t.Fatalf("review-samples cmd failed: %v", err)
	}
	if recorded.Method != "GET" || recorded.Path != "/reviews/samples" {
		t.Fatalf("unexpected request: %s %s", recorded.Method, recorded.Path)
	}
	if recorded.Query.Get("ids") != "r1,r2,r3" {
		t.Errorf("expected ids=r1,r2,r3, got %v", recorded.Query.Get("ids"))
	}
}
