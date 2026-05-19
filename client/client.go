package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type Client struct {
	BaseURL    string
	httpClient *http.Client
}

type authTransport struct {
	apiKey string
	base   http.RoundTripper
}

func (t *authTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	if t.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+t.apiKey)
	}
	return t.base.RoundTrip(req)
}

func New(baseURL, apiKey string) *Client {
	return &Client{
		BaseURL: baseURL,
		httpClient: &http.Client{
			Timeout:   30 * time.Second,
			Transport: &authTransport{apiKey: apiKey, base: http.DefaultTransport},
		},
	}
}

// Document represents a layer document for upsert/fetch.
type Document struct {
	ID         string         `json:"id"`
	Attributes map[string]any `json:"attributes,omitempty"`
	Vector     []float64      `json:"vector,omitempty"`
}

// UpsertRequest is the body for POST /v2/namespaces/{ns}.
type UpsertRequest struct {
	Upserts        []Document `json:"upserts"`
	DistanceMetric string     `json:"distance_metric,omitempty"`
}

// QueryRequest is the body for POST /v2/namespaces/{ns}/query.
type QueryRequest struct {
	Vector            []float64 `json:"vector"`
	TopK              int       `json:"top_k"`
	DistanceMetric    string    `json:"distance_metric,omitempty"`
	IncludeAttributes []string  `json:"include_attributes,omitempty"`
}

// QueryResult is a single result from a vector query.
type QueryResult struct {
	ID         string         `json:"id"`
	Dist       float64        `json:"dist"`
	Attributes map[string]any `json:"attributes,omitempty"`
}

// FetchRequest is the body for POST /v2/namespaces/{ns}/documents.
type FetchRequest struct {
	IDs               []string `json:"ids"`
	IncludeAttributes []string `json:"include_attributes,omitempty"`
}

// ScanResponse is the response from creating or polling a scan.
type ScanResponse struct {
	ID         string     `json:"id,omitempty"`
	Status     string     `json:"status,omitempty"`
	Data       []Document `json:"data,omitempty"`
	NextCursor string     `json:"next_cursor,omitempty"`
}

// Health checks GET /health.
func (c *Client) Health() (map[string]any, error) {
	resp, err := c.httpClient.Get(c.BaseURL + "/health")
	if err != nil {
		return nil, fmt.Errorf("health request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("health returned %d: %s", resp.StatusCode, string(body))
	}

	var result map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode health response: %w", err)
	}
	return result, nil
}

// Upsert sends documents to POST /v2/namespaces/{ns}.
func (c *Client) Upsert(namespace string, req UpsertRequest) error {
	body, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("failed to marshal upsert request: %w", err)
	}

	resp, err := c.httpClient.Post(
		fmt.Sprintf("%s/v2/namespaces/%s", c.BaseURL, namespace),
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return fmt.Errorf("upsert request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("upsert returned %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}

// Get fetches a single document via GET /v2/namespaces/{ns}/documents/{id}.
func (c *Client) Get(namespace, docID string) (*Document, error) {
	resp, err := c.httpClient.Get(
		fmt.Sprintf("%s/v2/namespaces/%s/documents/%s", c.BaseURL, namespace, docID),
	)
	if err != nil {
		return nil, fmt.Errorf("get request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("get returned %d: %s", resp.StatusCode, string(body))
	}

	var doc Document
	if err := json.NewDecoder(resp.Body).Decode(&doc); err != nil {
		return nil, fmt.Errorf("failed to decode document: %w", err)
	}
	return &doc, nil
}

// FetchMany fetches multiple documents via POST /v2/namespaces/{ns}/documents.
func (c *Client) FetchMany(namespace string, req FetchRequest) ([]Document, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal fetch request: %w", err)
	}

	resp, err := c.httpClient.Post(
		fmt.Sprintf("%s/v2/namespaces/%s/documents", c.BaseURL, namespace),
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("fetch request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("fetch returned %d: %s", resp.StatusCode, string(respBody))
	}

	var docs []Document
	if err := json.NewDecoder(resp.Body).Decode(&docs); err != nil {
		return nil, fmt.Errorf("failed to decode documents: %w", err)
	}
	return docs, nil
}

// Query performs a vector search via POST /v2/namespaces/{ns}/query.
func (c *Client) Query(namespace string, req QueryRequest) ([]QueryResult, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal query request: %w", err)
	}

	resp, err := c.httpClient.Post(
		fmt.Sprintf("%s/v2/namespaces/%s/query", c.BaseURL, namespace),
		"application/json",
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, fmt.Errorf("query request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("query returned %d: %s", resp.StatusCode, string(respBody))
	}

	var results []QueryResult
	if err := json.NewDecoder(resp.Body).Decode(&results); err != nil {
		return nil, fmt.Errorf("failed to decode query results: %w", err)
	}
	return results, nil
}

// CreateScan creates a scan via POST /v2/namespaces/{ns}/scans.
func (c *Client) CreateScan(namespace string) (*ScanResponse, error) {
	resp, err := c.httpClient.Post(
		fmt.Sprintf("%s/v2/namespaces/%s/scans", c.BaseURL, namespace),
		"application/json",
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("create scan request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("create scan returned %d: %s", resp.StatusCode, string(body))
	}

	var scan ScanResponse
	if err := json.NewDecoder(resp.Body).Decode(&scan); err != nil {
		return nil, fmt.Errorf("failed to decode scan response: %w", err)
	}
	return &scan, nil
}

// GetScan polls a scan via GET /v2/namespaces/{ns}/scans/{id}.
func (c *Client) GetScan(namespace, scanID string) (*ScanResponse, error) {
	resp, err := c.httpClient.Get(
		fmt.Sprintf("%s/v2/namespaces/%s/scans/%s", c.BaseURL, namespace, scanID),
	)
	if err != nil {
		return nil, fmt.Errorf("get scan request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("get scan returned %d: %s", resp.StatusCode, string(body))
	}

	var scan ScanResponse
	if err := json.NewDecoder(resp.Body).Decode(&scan); err != nil {
		return nil, fmt.Errorf("failed to decode scan response: %w", err)
	}
	return &scan, nil
}
