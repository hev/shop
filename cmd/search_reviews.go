package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/client/searchapi"
	"github.com/spf13/cobra"
)

var (
	reviewSearchQuery       string
	reviewSearchASIN        string
	reviewSearchTopK        int
	reviewSearchCategory    string
	reviewSearchCursor      string
	reviewSearchWithCount   bool
	reviewSearchMaxDistance float32
)

var searchReviewsCmd = &cobra.Command{
	Use:   "search-reviews",
	Short: "Search review chunks for one ASIN (GET /search/reviews)",
	RunE: func(cmd *cobra.Command, args []string) error {
		if reviewSearchQuery == "" {
			return fmt.Errorf("--query is required")
		}
		if reviewSearchASIN == "" {
			return fmt.Errorf("--asin is required")
		}
		c, err := newSearchClient()
		if err != nil {
			return err
		}
		params := &searchapi.SearchReviewsSearchReviewsGetParams{
			Q:           reviewSearchQuery,
			Asin:        reviewSearchASIN,
			TopK:        &reviewSearchTopK,
			WithCount:   &reviewSearchWithCount,
			MaxDistance: &reviewSearchMaxDistance,
		}
		if reviewSearchCategory != "" {
			params.Category = &reviewSearchCategory
		}
		if reviewSearchCursor != "" {
			params.Cursor = &reviewSearchCursor
		}
		resp, err := c.SearchReviewsSearchReviewsGetWithResponse(ctx(), params)
		if err != nil {
			return fmt.Errorf("review search request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("search-reviews", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	searchReviewsCmd.Flags().StringVar(&reviewSearchQuery, "query", "", "review-search query text (required)")
	searchReviewsCmd.Flags().StringVar(&reviewSearchASIN, "asin", "", "ASIN to scope the review search to (required)")
	searchReviewsCmd.Flags().IntVar(&reviewSearchTopK, "top-k", 10, "max review chunks to return")
	searchReviewsCmd.Flags().StringVar(&reviewSearchCategory, "category", "", "optional category filter")
	searchReviewsCmd.Flags().StringVar(&reviewSearchCursor, "cursor", "", "opaque cursor from a prior response's next_cursor")
	searchReviewsCmd.Flags().BoolVar(&reviewSearchWithCount, "with-count", false, "fan out an extra /result-count call within --max-distance")
	searchReviewsCmd.Flags().Float32Var(&reviewSearchMaxDistance, "max-distance", 0.4, "cosine-distance ceiling for --with-count")
	rootCmd.AddCommand(searchReviewsCmd)
}
