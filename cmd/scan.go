package cmd

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/spf13/cobra"
)

var scanCmd = &cobra.Command{
	Use:   "scan",
	Short: "Create a scan and poll for results",
	RunE: func(cmd *cobra.Command, args []string) error {
		fmt.Printf("creating scan on namespace %q...\n", namespace)
		scan, err := layerClient.CreateScan(namespace)
		if err != nil {
			return fmt.Errorf("create scan failed: %w", err)
		}
		fmt.Printf("scan created: id=%s\n", scan.ID)

		// Poll until complete or timeout.
		for i := 0; i < 30; i++ {
			result, err := layerClient.GetScan(namespace, scan.ID)
			if err != nil {
				return fmt.Errorf("get scan failed: %w", err)
			}

			if result.Status == "complete" || result.Status == "" {
				out, _ := json.MarshalIndent(result, "", "  ")
				fmt.Printf("scan complete (%d docs):\n%s\n", len(result.Data), string(out))
				return nil
			}

			fmt.Printf("scan status: %s, polling...\n", result.Status)
			time.Sleep(1 * time.Second)
		}

		return fmt.Errorf("scan timed out after 30s")
	},
}

func init() {
	rootCmd.AddCommand(scanCmd)
}
