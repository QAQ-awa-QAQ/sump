package protocol

import (
	"crypto/rand"
	"time"

	"github.com/oklog/ulid/v2"
)

// idEntropy 是包级熵源：保证同毫秒内 id 单调递增（内部带锁，线程安全）。
var idEntropy = ulid.Monotonic(rand.Reader, 0)

// NewID 生成消息 / 链路 id（ULID：时间有序 + 随机，形如 01J...）。
func NewID() string {
	return ulid.MustNew(ulid.Timestamp(time.Now()), idEntropy).String()
}
