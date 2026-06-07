package cmd

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/hev/shop/tests/client/indexerapi"
	"github.com/spf13/cobra"
)

// healthCmd pings both services. /healthz is only ALB-routed for the
// search service, so the indexer side rides /status instead — a 200
// from /status proves the indexer pod is reachable and the gateway
// pipeline is alive.
var healthCmd = &cobra.Command{
	Use:   "health",
	Short: "Liveness check for both hev-shop services",
	RunE: func(cmd *cobra.Command, args []string) error {
		search, err := newSearchClient()
		if err != nil {
			return err
		}
		searchResp, err := search.HealthzHealthzGetWithResponse(ctx())
		if err != nil {
			return fmt.Errorf("search /healthz failed: %w", err)
		}

		indexer, err := newIndexerClient()
		if err != nil {
			return err
		}
		indexerResp, err := indexer.StatusStatusGetWithResponse(
			ctx(), &indexerapi.StatusStatusGetParams{},
		)
		if err != nil {
			return fmt.Errorf("indexer /status failed: %w", err)
		}

		out := map[string]any{
			"search": map[string]any{
				"url":         resolvedSearchURL(),
				"status_code": searchResp.HTTPResponse.StatusCode,
				"body":        decodeOrRaw(searchResp.Body),
			},
			"indexer": map[string]any{
				"url":         resolvedIndexerURL(),
				"status_code": indexerResp.HTTPResponse.StatusCode,
				"body":        decodeOrRaw(indexerResp.Body),
			},
		}
		pretty, err := json.MarshalIndent(out, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(pretty))

		if searchResp.HTTPResponse.StatusCode != http.StatusOK ||
			indexerResp.HTTPResponse.StatusCode != http.StatusOK {
			return fmt.Errorf("one or more health probes returned non-200")
		}
		return nil
	},
}

func decodeOrRaw(body []byte) any {
	var generic any
	if err := json.Unmarshal(body, &generic); err == nil {
		return generic
	}
	return string(body)
}

func init() {
	rootCmd.AddCommand(healthCmd)
}
