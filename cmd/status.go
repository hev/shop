package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/client/indexerapi"
	"github.com/spf13/cobra"
)

var statusPipelineID string

var statusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show hev-shop indexing status (GET /status)",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newIndexerClient()
		if err != nil {
			return err
		}
		params := &indexerapi.StatusStatusGetParams{}
		if statusPipelineID != "" {
			params.PipelineId = &statusPipelineID
		}
		resp, err := c.StatusStatusGetWithResponse(ctx(), params)
		if err != nil {
			return fmt.Errorf("status request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("indexer", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	statusCmd.Flags().StringVar(&statusPipelineID, "pipeline-id", "", "pipeline id (defaults to indexer PIPELINE_ID)")
	rootCmd.AddCommand(statusCmd)
}
