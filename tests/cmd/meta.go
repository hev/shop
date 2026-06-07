package cmd

import (
	"fmt"
	"net/http"

	"github.com/hev/shop/tests/client/searchapi"
	"github.com/spf13/cobra"
)

var metaNamespace string

var metaCmd = &cobra.Command{
	Use:   "meta",
	Short: "Namespace metadata + per-category counts (GET /meta)",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newSearchClient()
		if err != nil {
			return err
		}
		params := &searchapi.MetaMetaGetParams{}
		if metaNamespace != "" {
			params.Namespace = &metaNamespace
		}
		resp, err := c.MetaMetaGetWithResponse(ctx(), params)
		if err != nil {
			return fmt.Errorf("meta request failed: %w", err)
		}
		if resp.HTTPResponse.StatusCode != http.StatusOK {
			return errorFromBody("meta", resp.HTTPResponse.StatusCode, resp.Body)
		}
		return printJSON(resp.Body)
	},
}

func init() {
	metaCmd.Flags().StringVar(&metaNamespace, "namespace", "", "override the target namespace")
	rootCmd.AddCommand(metaCmd)
}
