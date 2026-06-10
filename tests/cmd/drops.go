package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/tests/client/searchapi"
	"github.com/spf13/cobra"
)

var (
	dropsNamespace string
	dropsLimit     int
)

var dropsCmd = &cobra.Command{
	Use:   "drops",
	Short: "Recent catalog drops (GET /drops)",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newSearchClient()
		if err != nil {
			return err
		}
		params := &searchapi.DropsDropsGetParams{}
		if dropsNamespace != "" {
			params.Namespace = &dropsNamespace
		}
		if dropsLimit > 0 {
			params.Limit = &dropsLimit
		}
		resp, err := c.DropsDropsGetWithResponse(ctx(), params)
		if err != nil {
			return fmt.Errorf("drops request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("drops", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	dropsCmd.Flags().StringVar(&dropsNamespace, "namespace", "", "override the target namespace")
	dropsCmd.Flags().IntVar(&dropsLimit, "limit", 7, "maximum drops to return")
	rootCmd.AddCommand(dropsCmd)
}
