package tests

import (
	"path/filepath"
	"testing"

	"github.com/QAQ-awa-QAQ/sump/memory/store"
)

// TestStoreAppendRecent 验证落库、幂等与按会话查询。
func TestStoreAppendRecent(t *testing.T) {
	st, err := store.Open(filepath.Join(t.TempDir(), "m.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()

	for _, c := range []string{"a", "b", "c", "d"} {
		if err := st.Append("c1", "user", c); err != nil {
			t.Fatal(err)
		}
	}
	// 幂等：与上一条完全相同的消息不重复入库。
	if err := st.Append("c1", "user", "d"); err != nil {
		t.Fatal(err)
	}
	if err := st.Append("c2", "user", "x"); err != nil {
		t.Fatal(err)
	}

	got, err := st.Recent("c1", 3)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 || got[0].Content != "b" || got[1].Content != "c" || got[2].Content != "d" {
		t.Fatalf("Recent(c1,3) 不符: %+v", got)
	}

	all, err := st.Recent("c1", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != 4 || all[0].Content != "a" {
		t.Fatalf("Recent(c1,10) 不符: %+v", all)
	}

	other, err := st.Recent("c2", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(other) != 1 || other[0].Content != "x" {
		t.Fatalf("Recent(c2,10) 不符: %+v", other)
	}
}
