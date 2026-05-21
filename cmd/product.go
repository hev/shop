package cmd

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"
)

var productCmd = &cobra.Command{
	Use:   "product <asin>",
	Short: "Fetch a single product document (GET /product/{asin})",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newSearchClient()
		if err != nil {
			return err
		}
		resp, err := c.ProductProductAsinGetWithResponse(ctx(), args[0])
		if err != nil {
			return fmt.Errorf("product request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("product", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	rootCmd.AddCommand(productCmd)
}
