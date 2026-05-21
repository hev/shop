package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/client/searchapi"
	"github.com/spf13/cobra"
)

var (
	searchQuery       string
	searchTopK        int
	searchCategory    string
	searchTags        []string
	searchCursor      string
	searchWithCount   bool
	searchMaxDistance float32
	searchNamespace   string
)

var searchCmd = &cobra.Command{
	Use:   "search [query]",
	Short: "Semantic product search (POST /search)",
	Args:  cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		query := searchQuery
		if len(args) > 0 && args[0] != "" {
			query = args[0]
		}
		if query == "" {
			return fmt.Errorf("a query is required (positional arg or --query)")
		}
		body := searchapi.SearchRequest{
			Query:       query,
			MaxDistance: &searchMaxDistance,
			TopK:        &searchTopK,
			WithCount:   &searchWithCount,
		}
		if searchCategory != "" {
			body.Category = &searchCategory
		}
		if len(searchTags) > 0 {
			tags := normalizeCategories(searchTags)
			body.Tags = &tags
		}
		if searchCursor != "" {
			body.Cursor = &searchCursor
		}
		if searchNamespace != "" {
			body.Namespace = &searchNamespace
		}

		c, err := newSearchClient()
		if err != nil {
			return err
		}
		resp, err := c.SearchSearchPostWithResponse(ctx(), body)
		if err != nil {
			return fmt.Errorf("search request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("search", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	searchCmd.Flags().StringVar(&searchQuery, "query", "", "search query (alternative to positional arg)")
	searchCmd.Flags().IntVar(&searchTopK, "top-k", 10, "max results")
	searchCmd.Flags().StringVar(&searchCategory, "category", "", "filter by product category")
	searchCmd.Flags().StringSliceVar(&searchTags, "tags", nil, "filter by review-derived tags (comma-separated or repeatable)")
	searchCmd.Flags().StringVar(&searchCursor, "cursor", "", "opaque cursor from a prior /search response's next_cursor")
	searchCmd.Flags().BoolVar(&searchWithCount, "with-count", false, "fan out an extra /count call to estimate matches within --max-distance")
	searchCmd.Flags().Float32Var(&searchMaxDistance, "max-distance", 0.4, "cosine-distance ceiling for --with-count")
	searchCmd.Flags().StringVar(&searchNamespace, "namespace", "", "override the target namespace")
	rootCmd.AddCommand(searchCmd)
}
