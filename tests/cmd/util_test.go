package cmd

import (
	"reflect"
	"testing"
)

func TestNormalizeCategories(t *testing.T) {
	got := normalizeCategories([]string{
		" Electronics ",
		"Home and Kitchen",
		"electronics",
		"",
		"Books",
	})
	want := []string{"Electronics", "Home and Kitchen", "Books"}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("normalizeCategories() = %#v, want %#v", got, want)
	}
}
