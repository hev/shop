package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/client/searchapi"
	"github.com/spf13/cobra"
)

var (
	recommendASIN      string
	recommendTopK      int
	recommendCategory  string
	recommendNamespace string
)

var recommendCmd = &cobra.Command{
	Use:   "recommend [asin]",
	Short: "Visual similar-product recommendations (POST /recommend)",
	Long: `Returns the nearest CLIP-image neighbors for a seed ASIN. The
search service uses Layer's nearest_to_id query mode, so the seed's
stored vector never leaves the gateway. The seed ASIN itself is filtered
out so callers don't get the seed back as its own first hit.`,
	Args: cobra.MaximumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		asin := recommendASIN
		if len(args) > 0 && args[0] != "" {
			asin = args[0]
		}
		if asin == "" {
			return fmt.Errorf("a seed ASIN is required (positional arg or --asin)")
		}
		body := searchapi.RecommendRequest{
			Asin: asin,
			TopK: &recommendTopK,
		}
		if recommendCategory != "" {
			body.Category = &recommendCategory
		}
		if recommendNamespace != "" {
			body.Namespace = &recommendNamespace
		}

		c, err := newSearchClient()
		if err != nil {
			return err
		}
		resp, err := c.RecommendRecommendPostWithResponse(ctx(), body)
		if err != nil {
			return fmt.Errorf("recommend request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("recommend", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	recommendCmd.Flags().StringVar(&recommendASIN, "asin", "", "seed ASIN (alternative to positional arg)")
	recommendCmd.Flags().IntVar(&recommendTopK, "top-k", 10, "max recommendations")
	recommendCmd.Flags().StringVar(&recommendCategory, "category", "", "filter neighbors by product category")
	recommendCmd.Flags().StringVar(&recommendNamespace, "namespace", "", "override the target namespace")
	rootCmd.AddCommand(recommendCmd)
}
