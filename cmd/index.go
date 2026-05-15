package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

var (
	indexCount      int
	indexCategory   string
	indexCategories []string
	indexPipelineID string
	indexJobSize    int
)

type indexRequest struct {
	Count      int      `json:"count"`
	Category   string   `json:"category,omitempty"`
	Categories []string `json:"categories,omitempty"`
	PipelineID string   `json:"pipeline_id,omitempty"`
	Namespace  string   `json:"namespace,omitempty"`
	JobSize    int      `json:"job_size,omitempty"`
}

var indexCmd = &cobra.Command{
	Use:   "index",
	Short: "Queue Amazon product image indexing through the hev-shop indexer",
	RunE: func(cmd *cobra.Command, args []string) error {
		categories := normalizeCategories(indexCategories)
		categoryFlagChanged := cmd.Flags().Changed("category")
		if len(categories) > 0 && categoryFlagChanged {
			categories = normalizeCategories(append([]string{indexCategory}, categories...))
		}

		req := indexRequest{
			Count:      indexCount,
			PipelineID: indexPipelineID,
			Namespace:  namespace,
			JobSize:    indexJobSize,
		}
		if len(categories) > 0 {
			req.Categories = categories
		} else {
			req.Category = indexCategory
		}
		body, err := json.Marshal(req)
		if err != nil {
			return fmt.Errorf("marshal index request: %w", err)
		}

		client := &http.Client{Timeout: 30 * time.Second}
		url := strings.TrimRight(indexerURL, "/") + "/index"
		resp, err := client.Post(url, "application/json", bytes.NewReader(body))
		if err != nil {
			return fmt.Errorf("indexer request failed: %w", err)
		}
		defer resp.Body.Close()

		respBody, _ := io.ReadAll(resp.Body)
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("indexer returned %d: %s", resp.StatusCode, string(respBody))
		}

		var out any
		if err := json.Unmarshal(respBody, &out); err != nil {
			return fmt.Errorf("decode indexer response: %w", err)
		}
		pretty, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(pretty))
		return nil
	},
}

func normalizeCategories(categories []string) []string {
	out := make([]string, 0, len(categories))
	seen := make(map[string]struct{}, len(categories))
	for _, category := range categories {
		category = strings.TrimSpace(category)
		if category == "" {
			continue
		}
		key := strings.ToLower(category)
		if _, ok := seen[key]; ok {
			continue
		}
		out = append(out, category)
		seen[key] = struct{}{}
	}
	return out
}

func init() {
	indexCmd.Flags().IntVar(&indexCount, "count", 10000, "number of products to index (-1 for all rows in one job)")
	indexCmd.Flags().StringVar(&indexCategory, "category", "Electronics", "Amazon Reviews 2023 metadata category")
	indexCmd.Flags().StringSliceVar(
		&indexCategories,
		"categories",
		nil,
		"Amazon Reviews 2023 metadata categories (comma-separated or repeatable)",
	)
	indexCmd.Flags().StringVar(&indexPipelineID, "pipeline-id", "", "pipeline id (defaults to indexer PIPELINE_ID)")
	indexCmd.Flags().IntVar(&indexJobSize, "job-size", 10000, "products per extraction job")
	rootCmd.AddCommand(indexCmd)
}
