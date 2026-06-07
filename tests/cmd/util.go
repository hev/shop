package cmd

import "strings"

// normalizeCategories trims whitespace, drops empties, and dedupes
// case-insensitively while preserving first-seen casing.
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
