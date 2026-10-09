// Package longterm 是记忆服务的长期记忆库（SQLite）：条目写入 / 软删 / 读取。
// 与 store（会话库）**共享同一个 *sql.DB 句柄**（同进程同库——将来跨表事务才有原子性）。
// 检索（bigram 打分）见 rank.go：纯函数，不碰库。
package longterm

import (
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"
)

// Entry 是一条长期记忆条目。
type Entry struct {
	ID             int64
	Kind           string
	Content        string
	Priority       int
	ConversationID string
	CreatedAt      string
	UpdatedAt      string
}

// Store 是长期记忆库。
type Store struct {
	db *sql.DB
}

// Open 校验 / 建立 memories 表（db 由会话库提供——共享句柄是有意为之）。
func Open(db *sql.DB) (*Store, error) {
	s := &Store{db: db}
	if err := s.migrate(); err != nil {
		return nil, err
	}
	return s, nil
}

const schema = `
CREATE TABLE IF NOT EXISTS memories (
	id              INTEGER PRIMARY KEY AUTOINCREMENT,
	kind            TEXT NOT NULL,
	content         TEXT NOT NULL,
	priority        INTEGER NOT NULL DEFAULT 0,
	source          TEXT NOT NULL DEFAULT '',
	conversation_id TEXT,
	status          TEXT NOT NULL DEFAULT 'active',
	created_at      TEXT NOT NULL,
	updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status, priority DESC, id DESC);
`

// migrate 建表；占位期的 memories 表形状不同（从未写入过）——空表直接重建，非空则拒绝自动迁移。
func (s *Store) migrate() error {
	var name string
	err := s.db.QueryRow(`SELECT name FROM sqlite_master WHERE type='table' AND name='memories'`).Scan(&name)
	switch {
	case errors.Is(err, sql.ErrNoRows):
		_, err = s.db.Exec(schema)
		return err
	case err != nil:
		return err
	}

	rows, err := s.db.Query(`PRAGMA table_info(memories)`)
	if err != nil {
		return err
	}
	hasStatus := false
	for rows.Next() {
		var cid, notNull, pk int
		var cName, cType string
		var dflt sql.NullString
		if err := rows.Scan(&cid, &cName, &cType, &notNull, &dflt, &pk); err != nil {
			rows.Close()
			return err
		}
		if cName == "status" {
			hasStatus = true
		}
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return err
	}
	rows.Close()
	if hasStatus {
		_, err = s.db.Exec(schema)
		return err
	}

	var n int
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM memories`).Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return fmt.Errorf("memories 表是旧占位形状且有 %d 行数据，无法自动迁移（请人工处理后重试）", n)
	}
	if _, err := s.db.Exec(`DROP TABLE memories`); err != nil {
		return err
	}
	_, err = s.db.Exec(schema)
	return err
}

// Add 写入一条条目；已有相同（kind+content）的 active 条目时幂等跳过。
// source 记录写入方（调用方服务名）。
func (s *Store) Add(kind, content string, priority int, conversationID, source string) (int64, bool, error) {
	kind = strings.TrimSpace(kind)
	content = strings.TrimSpace(content)
	if kind == "" || content == "" {
		return 0, false, errors.New("kind 与 content 必填")
	}
	if priority < 0 {
		priority = 0
	}
	var id int64
	err := s.db.QueryRow(
		`SELECT id FROM memories WHERE status='active' AND kind=? AND content=? LIMIT 1`,
		kind, content,
	).Scan(&id)
	switch {
	case err == nil:
		return id, false, nil
	case !errors.Is(err, sql.ErrNoRows):
		return 0, false, err
	}

	now := time.Now().Format(time.RFC3339Nano)
	res, err := s.db.Exec(
		`INSERT INTO memories(kind, content, priority, source, conversation_id, status, created_at, updated_at)
		 VALUES(?,?,?,?,?,'active',?,?)`,
		kind, content, priority, source, nullIfEmpty(conversationID), now, now,
	)
	if err != nil {
		return 0, false, err
	}
	id, err = res.LastInsertId()
	return id, true, err
}

// Forget 软删一条条目（status='deleted'）；返回是否真的删到了。
func (s *Store) Forget(id int64) (bool, error) {
	res, err := s.db.Exec(
		`UPDATE memories SET status='deleted', updated_at=? WHERE id=? AND status='active'`,
		time.Now().Format(time.RFC3339Nano), id,
	)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	return n > 0, err
}

// ListActive 返回全部 active 条目（按 id 升序；v0 个人规模全量取出，检索在进程内做）。
func (s *Store) ListActive() ([]Entry, error) {
	rows, err := s.db.Query(
		`SELECT id, kind, content, priority, COALESCE(conversation_id,''), created_at, updated_at
		 FROM memories WHERE status='active' ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Entry
	for rows.Next() {
		var e Entry
		if err := rows.Scan(&e.ID, &e.Kind, &e.Content, &e.Priority, &e.ConversationID, &e.CreatedAt, &e.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func nullIfEmpty(s string) any {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	return s
}
