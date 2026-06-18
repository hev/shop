package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/tests/client/indexerapi"
	"github.com/spf13/cobra"
)

var (
	checkpointCatalogRun  string
	checkpointAllowFailed bool
)

var checkpointCmd = &cobra.Command{
	Use:   "checkpoint",
	Short: "Activate a catalog checkpoint after ingest stabilizes (POST /index/checkpoint)",
	RunE: func(cmd *cobra.Command, args []string) error {
		body := indexerapi.CheckpointActivationRequest{}
		if checkpointCatalogRun != "" {
			body.CatalogRunId = &checkpointCatalogRun
		}
		if cmd.Flags().Changed("allow-failed") {
			body.AllowFailed = &checkpointAllowFailed
		}

		c, err := newIndexerClient()
		if err != nil {
			return err
		}
		resp, err := c.ActivateCatalogCheckpointIndexCheckpointPostWithResponse(ctx(), body)
		if err != nil {
			return fmt.Errorf("indexer checkpoint request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("indexer", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	checkpointCmd.Flags().StringVar(
		&checkpointCatalogRun,
		"catalog-run-id",
		"",
		"checkpoint/drop label to activate (defaults to catalog-YYYY-MM-DD)",
	)
	checkpointCmd.Flags().BoolVar(
		&checkpointAllowFailed,
		"allow-failed",
		false,
		"allow checkpoint activation when pipelines have failed documents",
	)
	rootCmd.AddCommand(checkpointCmd)
}
