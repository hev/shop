package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/hev/shop/tests/client/indexerapi"
	"github.com/hev/shop/tests/client/searchapi"
	"github.com/spf13/cobra"
)

// CLI-wide flags. `apiBase` is the public ALB hostname; both services live
// behind it (path-routed). For local dev / port-forward setups, callers can
// override either service URL independently with --search-url / --indexer-url.
var (
	apiBase    string
	searchURL  string
	indexerURL string
)

var rootCmd = &cobra.Command{
	Use:   "shop",
	Short: "CLI for the hev-shop search + indexer APIs",
	Long: `shop is the command-line client for hev-shop's read API (search,
product, meta, drops, recommend) and indexer control plane (index, status).
Every endpoint described in search/openapi.json and indexer/openapi.json
has a matching subcommand here.`,
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func init() {
	rootCmd.PersistentFlags().StringVar(
		&apiBase, "api-base",
		envOrDefault("SHOP_API_BASE", "https://api.hev-shop.com"),
		"hev-shop API base URL (used unless --search-url / --indexer-url override it)",
	)
	rootCmd.PersistentFlags().StringVar(
		&searchURL, "search-url",
		os.Getenv("SHOP_SEARCH_URL"),
		"search service URL (defaults to --api-base)",
	)
	rootCmd.PersistentFlags().StringVar(
		&indexerURL, "indexer-url",
		os.Getenv("SHOP_INDEXER_URL"),
		"indexer service URL (defaults to --api-base)",
	)
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func resolvedSearchURL() string {
	if searchURL != "" {
		return strings.TrimRight(searchURL, "/")
	}
	return strings.TrimRight(apiBase, "/")
}

func resolvedIndexerURL() string {
	if indexerURL != "" {
		return strings.TrimRight(indexerURL, "/")
	}
	return strings.TrimRight(apiBase, "/")
}

// httpDoer is the shared HTTP client used by every generated API call.
// 30s matches the previous indexer-pointed commands.
func httpDoer() *http.Client {
	return &http.Client{Timeout: 30 * time.Second}
}

func newSearchClient() (*searchapi.ClientWithResponses, error) {
	return searchapi.NewClientWithResponses(
		resolvedSearchURL(),
		searchapi.WithHTTPClient(httpDoer()),
	)
}

func newIndexerClient() (*indexerapi.ClientWithResponses, error) {
	return indexerapi.NewClientWithResponses(
		resolvedIndexerURL(),
		indexerapi.WithHTTPClient(httpDoer()),
	)
}

func ctx() context.Context {
	return context.Background()
}

// printJSON pretty-prints a raw JSON body. If the body is not valid JSON
// (e.g. a plaintext error page from a misrouted ALB request), it prints
// the body as-is so the caller can still see what came back.
func printJSON(body []byte) error {
	if len(body) == 0 {
		return nil
	}
	var generic any
	if err := json.Unmarshal(body, &generic); err != nil {
		fmt.Println(string(body))
		return nil
	}
	out, err := json.MarshalIndent(generic, "", "  ")
	if err != nil {
		return err
	}
	fmt.Println(string(out))
	return nil
}

// errorFromBody turns a non-2xx response into a CLI error, including the
// response body so the user sees the upstream detail.
func errorFromBody(label string, status int, body []byte) error {
	return fmt.Errorf("%s returned %d: %s", label, status, strings.TrimSpace(string(body)))
}
