package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"benchapp/internal/domain"

	"go.loglayer.dev/v3"
)

// Suite paritas: kasus dibaca dari contract-tests/parity-cases/cases.json (dipakai juga oleh suite Swift).

type parityCase struct {
	ID      string          `json:"id"`
	Kind    string          `json:"kind"`
	Input   json.RawMessage `json:"input"`
	Request *struct {
		Method string          `json:"method"`
		Path   string          `json:"path"`
		Body   json.RawMessage `json:"body"`
	} `json:"request"`
	Expect map[string]any `json:"expect"`
}

type fakeRepo struct{}

var fakeTime = time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)

func fakeOrder(id int64) domain.Order {
	return domain.Order{ID: id, UserID: 1, Status: "pending", TotalCents: 1000 * int(id), Note: "n", CreatedAt: fakeTime, UpdatedAt: fakeTime}
}

func (fakeRepo) GetUser(_ context.Context, id int64) (domain.User, error) {
	if id != 1 {
		return domain.User{}, domain.ErrNotFound
	}
	return domain.User{ID: 1, Name: "Fake User", Email: "fake@example.test", CreatedAt: fakeTime}, nil
}

func (fakeRepo) ListOrders(_ context.Context, _ int64, limit int) ([]domain.Order, error) {
	all := []domain.Order{fakeOrder(3), fakeOrder(2), fakeOrder(1)}
	if limit < len(all) {
		all = all[:limit]
	}
	return all, nil
}

func (f fakeRepo) GetUserWithOrders(ctx context.Context, id int64) (domain.UserWithOrders, error) {
	u, err := f.GetUser(ctx, id)
	if err != nil {
		return domain.UserWithOrders{}, err
	}
	o, _ := f.ListOrders(ctx, id, 100)
	return domain.UserWithOrders{User: u, Orders: o}, nil
}

func (fakeRepo) CreateOrder(_ context.Context, in domain.CreateOrderInput) (domain.Order, error) {
	return domain.Order{ID: 101, UserID: in.UserID, Status: in.Status, TotalCents: in.TotalCents, Note: in.Note, CreatedAt: fakeTime, UpdatedAt: fakeTime}, nil
}

func (fakeRepo) UpdateOrderStatus(_ context.Context, id int64, status string) (domain.Order, error) {
	if id != 1 {
		return domain.Order{}, domain.ErrNotFound
	}
	o := fakeOrder(1)
	o.Status = status
	return o, nil
}

func (fakeRepo) PayOrder(_ context.Context, id int64) (domain.PayResult, error) {
	if id != 1 {
		return domain.PayResult{}, domain.ErrNotFound
	}
	o := fakeOrder(1)
	o.Status = domain.StatusPaid
	return domain.PayResult{Order: o, Payment: domain.Payment{ID: 1, OrderID: 1, AmountCents: o.TotalCents, CreatedAt: fakeTime}}, nil
}

// subset: setiap kunci pada want harus ada dan sama pada got (objek rekursif; array sama panjang dan per elemen).
func subset(want, got any) bool {
	switch w := want.(type) {
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok {
			return false
		}
		for k, wv := range w {
			if gv, ok := g[k]; !ok || !subset(wv, gv) {
				return false
			}
		}
		return true
	case []any:
		g, ok := got.([]any)
		if !ok || len(g) != len(w) {
			return false
		}
		for i := range w {
			if !subset(w[i], g[i]) {
				return false
			}
		}
		return true
	default:
		return reflect.DeepEqual(want, got)
	}
}

func checkResult(t *testing.T, exp map[string]any, err error, extra map[string]any) {
	t.Helper()
	if want, ok := exp["error"].(string); ok {
		if err == nil || err.Error() != want {
			t.Fatalf("error = %v, want %q", err, want)
		}
		return
	}
	if err != nil {
		t.Fatalf("tidak diharapkan error: %v", err)
	}
	for k, v := range extra {
		if want, ok := exp[k]; ok && !reflect.DeepEqual(float64Of(want), float64Of(v)) {
			t.Fatalf("%s = %v, want %v", k, v, want)
		}
	}
}

func float64Of(v any) any {
	switch n := v.(type) {
	case int:
		return float64(n)
	case int64:
		return float64(n)
	}
	return v
}

func TestParity(t *testing.T) {
	path := filepath.Join("..", "..", "..", "contract-tests", "parity-cases", "cases.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var file struct {
		Cases []parityCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	var ran []string
	router := NewRouter(&API{Users: fakeRepo{}, Orders: fakeRepo{}}, loglayer.NewMock())

	for _, c := range file.Cases {
		ran = append(ran, c.ID)
		t.Run(c.ID, func(t *testing.T) {
			switch c.Kind {
			case "validate_order":
				var in domain.CreateOrderInput
				if err := json.Unmarshal(c.Input, &in); err != nil {
					t.Fatal(err)
				}
				err := in.Normalize()
				checkResult(t, c.Expect, err, map[string]any{"status": in.Status})
			case "validate_status":
				var s string
				_ = json.Unmarshal(c.Input, &s)
				checkResult(t, c.Expect, domain.UpdateOrderInput{Status: s}.Validate(), nil)
			case "validate_echo":
				var in domain.EchoRequest
				if err := json.Unmarshal(c.Input, &in); err != nil {
					t.Fatal(err)
				}
				checkResult(t, c.Expect, in.Validate(), nil)
			case "parse_limit":
				var s string
				_ = json.Unmarshal(c.Input, &s)
				v, err := domain.ParseLimit(s)
				checkResult(t, c.Expect, err, map[string]any{"value": v})
			case "parse_id":
				var s string
				_ = json.Unmarshal(c.Input, &s)
				v, err := domain.ParseID(s)
				checkResult(t, c.Expect, err, map[string]any{"value": v})
			case "bench_json":
				b, _ := json.Marshal(domain.NewBenchPayload())
				var m map[string]any
				_ = json.Unmarshal(b, &m)
				if len(m) != int(c.Expect["keys"].(float64)) {
					t.Fatalf("keys = %d", len(m))
				}
				if len(b) < int(c.Expect["min_bytes"].(float64)) || len(b) > int(c.Expect["max_bytes"].(float64)) {
					t.Fatalf("bytes = %d", len(b))
				}
				arr := m[c.Expect["array_key"].(string)].([]any)
				if len(arr) != int(c.Expect["array_len"].(float64)) {
					t.Fatalf("array_len = %d", len(arr))
				}
			case "handler":
				var body *bytes.Reader
				if len(c.Request.Body) == 0 {
					body = bytes.NewReader(nil)
				} else if c.Request.Body[0] == '"' {
					var s string
					_ = json.Unmarshal(c.Request.Body, &s)
					body = bytes.NewReader([]byte(s))
				} else {
					body = bytes.NewReader(c.Request.Body)
				}
				req := httptest.NewRequest(c.Request.Method, c.Request.Path, body)
				rec := httptest.NewRecorder()
				router.ServeHTTP(rec, req)
				if want := int(c.Expect["status"].(float64)); rec.Code != want {
					t.Fatalf("status = %d, want %d (%s)", rec.Code, want, rec.Body.String())
				}
				var got any
				if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
					t.Fatalf("body bukan JSON: %v", err)
				}
				if want, ok := c.Expect["json"]; ok && !subset(want, got) {
					t.Fatalf("json = %s, want subset %v", rec.Body.String(), want)
				}
				if n, ok := c.Expect["array_len"].(float64); ok {
					if arr, _ := got.([]any); len(arr) != int(n) {
						t.Fatalf("array_len = %d, want %v", len(arr), n)
					}
				}
				if n, ok := c.Expect["orders_len"].(float64); ok {
					if arr, _ := got.(map[string]any)["orders"].([]any); len(arr) != int(n) {
						t.Fatalf("orders_len = %d, want %v", len(arr), n)
					}
				}
				if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
					t.Fatalf("content-type = %q", ct)
				}
			default:
				t.Fatalf("kind tidak dikenal: %s", c.Kind)
			}
		})
	}
	if out := os.Getenv("PARITY_REPORT"); out != "" {
		_ = os.WriteFile(out, []byte(strings.Join(ran, "\n")+"\n"), 0o644)
	}
	if len(ran) < 20 {
		t.Fatalf("kasus paritas < 20 (%d)", len(ran))
	}
}
