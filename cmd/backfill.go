package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

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
)

type backfillRequest struct {
	Category          string   `json:"category"`
	Asins             []string `json:"asins,omitempty"`
	ProductLimit      int      `json:"product_limit"`
	ReviewsPerProduct *int     `json:"reviews_per_product,omitempty"`
	MaxTotalReviews   *int     `json:"max_total_reviews,omitempty"`
	Stages            []string `json:"stages,omitempty"`
	PipelineID        string   `json:"pipeline_id,omitempty"`
	Namespace         string   `json:"namespace,omitempty"`
}

var backfillCmd = &cobra.Command{
	Use:   "backfill",
	Short: "Backfill reviews and classification for existing products",
	Long: `Enqueue a backfill job that re-stages reviews (and optionally re-runs
aggregation) for products already in the namespace. The extraction worker picks
the job up and feeds the review-embed / review-classify / review-aggregate
pipelines that the existing workers consume.`,
	RunE: func(cmd *cobra.Command, args []string) error {
		asins := normalizeCategories(backfillAsins)
		stages := normalizeCategories(backfillStages)

		req := backfillRequest{
			Category:     backfillCategory,
			Asins:        asins,
			ProductLimit: backfillProductLimit,
			Stages:       stages,
			PipelineID:   backfillPipelineID,
			Namespace:    namespace,
		}
		if cmd.Flags().Changed("reviews-per-product") {
			v := backfillReviewsPerProduct
			req.ReviewsPerProduct = &v
		}
		if cmd.Flags().Changed("max-total-reviews") {
			v := backfillMaxTotalReviews
			req.MaxTotalReviews = &v
		}

		body, err := json.Marshal(req)
		if err != nil {
			return fmt.Errorf("marshal backfill request: %w", err)
		}

		client := &http.Client{Timeout: 30 * time.Second}
		url := strings.TrimRight(indexerURL, "/") + "/backfill"
		resp, err := client.Post(url, "application/json", bytes.NewReader(body))
		if err != nil {
			return fmt.Errorf("indexer request failed: %w", err)
		}
		defer resp.Body.Close()

		respBody, _ := io.ReadAll(resp.Body)
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("indexer returned %d: %s", resp.StatusCode, string(respBody))
		}

		var out any
		if err := json.Unmarshal(respBody, &out); err != nil {
			return fmt.Errorf("decode indexer response: %w", err)
		}
		pretty, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(pretty))
		return nil
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
	rootCmd.AddCommand(backfillCmd)
}
