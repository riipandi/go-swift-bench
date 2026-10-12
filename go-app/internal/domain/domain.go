// Package domain berisi model dan aturan validasi. Tidak bergantung pada paket lain di aplikasi.
package domain

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

var ErrNotFound = errors.New("not found")

// ValidationError adalah kesalahan masukan (HTTP 400).
type ValidationError struct{ Msg string }

func (e *ValidationError) Error() string { return e.Msg }

func invalid(format string, a ...any) error { return &ValidationError{Msg: fmt.Sprintf(format, a...)} }

const (
	StatusPending   = "pending"
	StatusPaid      = "paid"
	StatusShipped   = "shipped"
	StatusCancelled = "cancelled"

	DefaultLimit = 20
	MaxLimit     = 100
	MaxNoteLen   = 200
	MaxTotal     = 10_000_000

	MsgInvalidBody   = "invalid JSON body"
	MsgInvalidID     = "invalid id"
	MsgInvalidStatus = "status must be one of pending, paid, shipped, cancelled"
)

type User struct {
	ID        int64     `json:"id"`
	Name      string    `json:"name"`
	Email     string    `json:"email"`
	CreatedAt time.Time `json:"created_at"`
}

type Order struct {
	ID         int64     `json:"id"`
	UserID     int64     `json:"user_id"`
	Status     string    `json:"status"`
	TotalCents int       `json:"total_cents"`
	Note       string    `json:"note"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

type UserWithOrders struct {
	User
	Orders []Order `json:"orders"`
}

type Payment struct {
	ID          int64     `json:"id"`
	OrderID     int64     `json:"order_id"`
	AmountCents int       `json:"amount_cents"`
	CreatedAt   time.Time `json:"created_at"`
}

type PayResult struct {
	Order   Order   `json:"order"`
	Payment Payment `json:"payment"`
}

// CreateOrderInput adalah body POST /orders.
type CreateOrderInput struct {
	UserID     int64  `json:"user_id"`
	TotalCents int    `json:"total_cents"`
	Status     string `json:"status"`
	Note       string `json:"note"`
}

// UpdateOrderInput adalah body PUT /orders/{id}.
type UpdateOrderInput struct {
	Status string `json:"status"`
}

func ValidStatus(s string) bool {
	switch s {
	case StatusPending, StatusPaid, StatusShipped, StatusCancelled:
		return true
	}
	return false
}

// Normalize menerapkan status default dan memvalidasi masukan.
func (in *CreateOrderInput) Normalize() error {
	if in.UserID <= 0 {
		return invalid("user_id must be positive")
	}
	if in.TotalCents < 0 || in.TotalCents > MaxTotal {
		return invalid("total_cents must be between 0 and 10000000")
	}
	if in.Status == "" {
		in.Status = StatusPending
	} else if !ValidStatus(in.Status) {
		return invalid(MsgInvalidStatus)
	}
	if utf8.RuneCountInString(in.Note) > MaxNoteLen {
		return invalid("note must be at most 200 characters")
	}
	return nil
}

func (in UpdateOrderInput) Validate() error {
	if !ValidStatus(in.Status) {
		return invalid(MsgInvalidStatus)
	}
	return nil
}

// ParseID mengurai id path.
func ParseID(s string) (int64, error) {
	id, err := strconv.ParseInt(s, 10, 64)
	if err != nil || id <= 0 {
		return 0, invalid(MsgInvalidID)
	}
	return id, nil
}

// ParseLimit mengurai ?limit= (default 20, 1..100).
func ParseLimit(s string) (int, error) {
	if s == "" {
		return DefaultLimit, nil
	}
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 || n > MaxLimit {
		return 0, invalid("limit must be between 1 and 100")
	}
	return n, nil
}

// --- payload benchmark tanpa database ---

type EchoAddress struct {
	Street  string `json:"street"`
	City    string `json:"city"`
	Zip     string `json:"zip"`
	Country string `json:"country"`
}

type EchoCustomer struct {
	ID      int64       `json:"id"`
	Name    string      `json:"name"`
	Email   string      `json:"email"`
	Address EchoAddress `json:"address"`
}

type EchoItem struct {
	SKU        string   `json:"sku"`
	Name       string   `json:"name"`
	Qty        int      `json:"qty"`
	PriceCents int      `json:"price_cents"`
	Labels     []string `json:"labels"`
}

type EchoRequest struct {
	RequestID string       `json:"request_id"`
	Customer  EchoCustomer `json:"customer"`
	Items     []EchoItem   `json:"items"`
	Tags      []string     `json:"tags"`
	Note      string       `json:"note"`
}

func (e *EchoRequest) Validate() error {
	if e.RequestID == "" {
		return invalid("request_id is required")
	}
	if e.Customer.ID <= 0 {
		return invalid("customer.id must be positive")
	}
	if !strings.Contains(e.Customer.Email, "@") {
		return invalid("customer.email is invalid")
	}
	if len(e.Items) < 1 || len(e.Items) > 50 {
		return invalid("items must contain 1 to 50 entries")
	}
	for i, it := range e.Items {
		if it.Qty < 1 {
			return invalid("items[%d].qty must be at least 1", i)
		}
		if it.PriceCents < 0 {
			return invalid("items[%d].price_cents must not be negative", i)
		}
	}
	if len(e.Tags) > 20 {
		return invalid("tags must contain at most 20 entries")
	}
	return nil
}

// BenchPayload: objek tetap ~1 KB (20 field + satu array kecil), dibuat di memori per request.
type BenchPayload struct {
	ID           int64    `json:"id"`
	UUID         string   `json:"uuid"`
	Name         string   `json:"name"`
	Title        string   `json:"title"`
	Summary      string   `json:"summary"`
	Description  string   `json:"description"`
	Category     string   `json:"category"`
	Status       string   `json:"status"`
	Active       bool     `json:"active"`
	Verified     bool     `json:"verified"`
	Score        int      `json:"score"`
	Rank         int      `json:"rank"`
	Level        int      `json:"level"`
	Views        int64    `json:"views"`
	BalanceCents int64    `json:"balance_cents"`
	Currency     string   `json:"currency"`
	Country      string   `json:"country"`
	City         string   `json:"city"`
	Email        string   `json:"email"`
	CreatedAt    string   `json:"created_at"`
	Tags         []string `json:"tags"`
}

const benchDescription = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. " +
	"Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. " +
	"Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. " +
	"Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."

func NewBenchPayload() BenchPayload {
	return BenchPayload{
		ID:           1234567,
		UUID:         "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b",
		Name:         "Benchmark Subject",
		Title:        "A fixed object used to measure framework and JSON overhead",
		Summary:      "Built in memory on every request, no database involved.",
		Description:  benchDescription,
		Category:     "benchmark",
		Status:       "active",
		Active:       true,
		Verified:     true,
		Score:        98,
		Rank:         7,
		Level:        42,
		Views:        9876543210,
		BalanceCents: 123456789,
		Currency:     "IDR",
		Country:      "ID",
		City:         "Jakarta",
		Email:        "subject@example.test",
		CreatedAt:    "2025-01-01T00:00:00Z",
		Tags:         []string{"alpha", "beta", "gamma", "delta", "epsilon", "zeta"},
	}
}
