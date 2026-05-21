package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/client/indexerapi"
	"github.com/spf13/cobra"
)

var (
	backfillCategory          string
	backfillAsins             []string
	backfillProductLimit      int
	backfillReviewsPerProduct int
	backfillMaxTotalReviews   int
	backfillStages            []string
	backfillPipelineID        string
	backfillNamespace         string
)

var backfillCmd = &cobra.Command{
	Use:   "backfill",
	Short: "Backfill reviews and classification for existing products (POST /backfill)",
	Long: `Enqueue a backfill job that re-stages reviews (and optionally re-runs
aggregation) for products already in the namespace. The extraction worker picks
the job up and feeds the review-embed / review-classify / review-aggregate
pipelines that the existing workers consume.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		body := indexerapi.BackfillRequest{
			Category:     backfillCategory,
			ProductLimit: &backfillProductLimit,
		}
		asins := normalizeCategories(backfillAsins)
		if len(asins) > 0 {
			body.Asins = &asins
		}
		stages := normalizeCategories(backfillStages)
		if len(stages) > 0 {
			body.Stages = &stages
		}
		if cmd.Flags().Changed("reviews-per-product") {
			v := backfillReviewsPerProduct
			body.ReviewsPerProduct = &v
		}
		if cmd.Flags().Changed("max-total-reviews") {
			v := backfillMaxTotalReviews
			body.MaxTotalReviews = &v
		}
		if backfillPipelineID != "" {
			pid := backfillPipelineID
			body.PipelineId = &pid
		}
		if backfillNamespace != "" {
			ns := backfillNamespace
			body.Namespace = &ns
		}

		c, err := newIndexerClient()
		if err != nil {
			return err
		}
		resp, err := c.BackfillBackfillPostWithResponse(ctx(), body)
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
	backfillCmd.Flags().StringVar(&backfillCategory, "category", "Electronics", "HF dataset category (required)")
	backfillCmd.Flags().StringSliceVar(&backfillAsins, "asins", nil, "Explicit ASIN list (comma-separated or repeatable); overrides --product-limit when set")
	backfillCmd.Flags().IntVar(&backfillProductLimit, "product-limit", 1000, "Cap how many products to backfill when --asins is not set (-1 = unlimited)")
	backfillCmd.Flags().IntVar(&backfillReviewsPerProduct, "reviews-per-product", 0, "Cap reviews staged per ASIN (defaults to server setting)")
	backfillCmd.Flags().IntVar(&backfillMaxTotalReviews, "max-total-reviews", 0, "Global cap on reviews staged across the job (omit for unlimited)")
	backfillCmd.Flags().StringSliceVar(&backfillStages, "stages", nil, "Subset of embed,classify,aggregate (default: all three)")
	backfillCmd.Flags().StringVar(&backfillPipelineID, "pipeline-id", "", "Product pipeline id (defaults to indexer PIPELINE_ID)")
	backfillCmd.Flags().StringVar(&backfillNamespace, "namespace", "", "target namespace (defaults to indexer NAMESPACE)")
	rootCmd.AddCommand(backfillCmd)
}
