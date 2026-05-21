package cmd

import (
	"fmt"
	"net/http"
	"strings"

	"github.com/hev/shop/client/searchapi"
	"github.com/spf13/cobra"
)

var (
	reviewSamplesASIN string
	reviewSamplesIDs  []string
)

var reviewSamplesCmd = &cobra.Command{
	Use:   "review-samples",
	Short: "Fetch verbatim review chunks by ID (GET /reviews/samples)",
	RunE: func(cmd *cobra.Command, args []string) error {
		if reviewSamplesASIN == "" {
			return fmt.Errorf("--asin is required")
		}
		if len(reviewSamplesIDs) == 0 {
			return fmt.Errorf("--ids is required (comma-separated or repeatable)")
		}
		c, err := newSearchClient()
		if err != nil {
			return err
		}
		params := &searchapi.ReviewSamplesReviewsSamplesGetParams{
			Asin: reviewSamplesASIN,
			Ids:  strings.Join(reviewSamplesIDs, ","),
		}
		resp, err := c.ReviewSamplesReviewsSamplesGetWithResponse(ctx(), params)
		if err != nil {
			return fmt.Errorf("review samples request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("review-samples", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	reviewSamplesCmd.Flags().StringVar(&reviewSamplesASIN, "asin", "", "ASIN owning the review chunks (required)")
	reviewSamplesCmd.Flags().StringSliceVar(&reviewSamplesIDs, "ids", nil, "review IDs (comma-separated or repeatable, max 50)")
	rootCmd.AddCommand(reviewSamplesCmd)
}
