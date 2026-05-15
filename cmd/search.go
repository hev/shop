package cmd

import (
	"fmt"

	"github.com/spf13/cobra"
)

var searchCmd = &cobra.Command{
	Use:   "search",
	Short: "Semantic search over reviews (phase 2)",
	RunE: func(cmd *cobra.Command, args []string) error {
		fmt.Println("not yet implemented (phase 2): will embed query text and perform vector search")
		return nil
	},
}

func init() {
	searchCmd.Flags().String("query", "", "search query text")
	rootCmd.AddCommand(searchCmd)
}
