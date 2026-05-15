package cmd

import (
	"fmt"
	"os"

	"github.com/hev/shop/client"
	"github.com/spf13/cobra"
)

var (
	gatewayURL  string
	indexerURL  string
	namespace   string
	layerClient *client.Client
)

var rootCmd = &cobra.Command{
	Use:   "hev-shop",
	Short: "CLI for hev-layer demo with Amazon Reviews dataset",
	PersistentPreRun: func(cmd *cobra.Command, args []string) {
		layerClient = client.New(gatewayURL)
	},
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func init() {
	rootCmd.PersistentFlags().StringVar(&gatewayURL, "gateway-url", envOrDefault("LAYER_GATEWAY_URL", "http://localhost:8080"), "layer-gateway URL")
	rootCmd.PersistentFlags().StringVar(&indexerURL, "indexer-url", envOrDefault("HEV_SHOP_INDEXER_URL", "http://localhost:8090"), "hev-shop indexer URL")
	rootCmd.PersistentFlags().StringVar(&namespace, "namespace", envOrDefault("NAMESPACE", "amazon-products"), "target namespace")
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
