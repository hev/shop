package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/client/indexerapi"
	"github.com/spf13/cobra"
)

var (
	indexCount      int
	indexCategory   string
	indexCategories []string
	indexPipelineID string
	indexJobSize    int
	indexNamespace  string
)

var indexCmd = &cobra.Command{
	Use:   "index",
	Short: "Queue Amazon product image indexing (POST /index)",
	RunE: func(cmd *cobra.Command, args []string) error {
		body := indexerapi.IndexRequest{}
		categories := normalizeCategories(indexCategories)
		if len(categories) > 0 && cmd.Flags().Changed("category") {
			categories = normalizeCategories(append([]string{indexCategory}, categories...))
		}
		if len(categories) > 0 {
			body.Categories = &categories
		} else {
			cat := indexCategory
			body.Category = &cat
		}
		count := indexCount
		body.Count = &count
		jobSize := indexJobSize
		body.JobSize = &jobSize
		if indexPipelineID != "" {
			pid := indexPipelineID
			body.PipelineId = &pid
		}
		if indexNamespace != "" {
			ns := indexNamespace
			body.Namespace = &ns
		}

		c, err := newIndexerClient()
		if err != nil {
			return err
		}
		resp, err := c.IndexProductsIndexPostWithResponse(ctx(), body)
		if err != nil {
			return fmt.Errorf("indexer request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("indexer", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	indexCmd.Flags().IntVar(&indexCount, "count", 10000, "number of products to index (-1 for all rows in one job)")
	indexCmd.Flags().StringVar(&indexCategory, "category", "Electronics", "Amazon Reviews 2023 metadata category")
	indexCmd.Flags().StringSliceVar(
		&indexCategories,
		"categories",
		nil,
		"Amazon Reviews 2023 metadata categories (comma-separated or repeatable)",
	)
	indexCmd.Flags().StringVar(&indexPipelineID, "pipeline-id", "", "pipeline id (defaults to indexer PIPELINE_ID)")
	indexCmd.Flags().IntVar(&indexJobSize, "job-size", 10000, "products per extraction job")
	indexCmd.Flags().StringVar(&indexNamespace, "namespace", "", "target namespace (defaults to indexer NAMESPACE)")
	rootCmd.AddCommand(indexCmd)
}
