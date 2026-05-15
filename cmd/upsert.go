package cmd

import (
	"encoding/json"
	"fmt"

	"github.com/hev/shop/client"
	"github.com/spf13/cobra"
)

var upsertCmd = &cobra.Command{
	Use:   "upsert",
	Short: "Upsert a sample Amazon review doc and fetch it back",
	RunE: func(cmd *cobra.Command, args []string) error {
		doc := client.Document{
			ID: "sample-review-001",
			Attributes: map[string]any{
				"title":          "Great wireless earbuds",
				"text":           "These earbuds have excellent sound quality and battery life. Comfortable fit for long listening sessions.",
				"rating":         5,
				"helpful_vote":   42,
				"verified":       true,
				"user_id":        "user-demo-001",
				"product_id":     "product-demo-001",
				"product_title":  "Wireless Bluetooth Earbuds",
				"category":       "Electronics",
				"average_rating": 4.3,
				"price":          29.99,
			},
		}

		fmt.Printf("upserting doc %q into namespace %q...\n", doc.ID, namespace)
		err := layerClient.Upsert(namespace, client.UpsertRequest{
			Upserts:        []client.Document{doc},
			DistanceMetric: "cosine_distance",
		})
		if err != nil {
			return fmt.Errorf("upsert failed: %w", err)
		}
		fmt.Println("upsert ok")

		fmt.Printf("fetching doc %q...\n", doc.ID)
		fetched, err := layerClient.Get(namespace, doc.ID)
		if err != nil {
			return fmt.Errorf("fetch failed: %w", err)
		}

		out, _ := json.MarshalIndent(fetched, "", "  ")
		fmt.Println("round-trip ok:")
		fmt.Println(string(out))
		return nil
	},
}

func init() {
	rootCmd.AddCommand(upsertCmd)
}
