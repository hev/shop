package cmd

import (
	"encoding/json"
	"fmt"

	"github.com/spf13/cobra"
)

var healthCmd = &cobra.Command{
	Use:   "health",
	Short: "Check layer-gateway health",
	RunE: func(cmd *cobra.Command, args []string) error {
		result, err := layerClient.Health()
		if err != nil {
			return fmt.Errorf("gateway unreachable: %w", err)
		}
		out, _ := json.MarshalIndent(result, "", "  ")
		fmt.Println(string(out))
		return nil
	},
}

func init() {
	rootCmd.AddCommand(healthCmd)
}
