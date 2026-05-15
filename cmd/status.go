package cmd

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

var statusPipelineID string

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show hev-shop indexing status",
	RunE: func(cmd *cobra.Command, args []string) error {
		client := &http.Client{Timeout: 30 * time.Second}
		endpoint := strings.TrimRight(indexerURL, "/") + "/status"
		if statusPipelineID != "" {
			values := url.Values{}
			values.Set("pipeline_id", statusPipelineID)
			endpoint += "?" + values.Encode()
		}

		resp, err := client.Get(endpoint)
		if err != nil {
			return fmt.Errorf("status request failed: %w", err)
		}
		defer resp.Body.Close()

		respBody, _ := io.ReadAll(resp.Body)
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("indexer returned %d: %s", resp.StatusCode, string(respBody))
		}

		var out any
		if err := json.Unmarshal(respBody, &out); err != nil {
			return fmt.Errorf("decode status response: %w", err)
		}
		pretty, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(pretty))
		return nil
	},
}

func init() {
	statusCmd.Flags().StringVar(&statusPipelineID, "pipeline-id", "", "pipeline id (defaults to indexer PIPELINE_ID)")
	rootCmd.AddCommand(statusCmd)
}
