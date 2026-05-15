package cmd

import (
	"fmt"

	"github.com/spf13/cobra"
)

var recommendCmd = &cobra.Command{
	Use:   "recommend",
	Short: "Visual product recommendations via CLIP (phase 3)",
	RunE: func(cmd *cobra.Command, args []string) error {
		fmt.Println("not yet implemented (phase 3): will use CLIP embeddings for visual product recommendations")
		return nil
	},
}

func init() {
	rootCmd.AddCommand(recommendCmd)
}
