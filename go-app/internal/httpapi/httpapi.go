// Package httpapi: router chi, handler, dan middleware. Hanya bergantung pada antarmuka kecil store.UserRepository dan store.OrderRepository.
package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"benchapp/internal/domain"
	"benchapp/internal/store"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"go.loglayer.dev/integrations/loghttp/v3"
	"go.loglayer.dev/v3"
)

type API struct {
	Users  store.UserRepository
	Orders store.OrderRepository
}

type errorBody struct {
	Error string `json:"error"`
}

// NewRouter memasang Recoverer lalu loghttp.Middleware (urutan sesuai PRD).
func NewRouter(a *API, log *loglayer.LogLayer) http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.Recoverer)
	r.Use(loghttp.Middleware(log, loghttp.Config{}))

	r.Get("/healthz", a.healthz)
	r.Get("/bench/json", a.benchJSON)
	r.Post("/bench/echo", a.benchEcho)
	r.Get("/users/{id}", a.getUser)
	r.Get("/users/{id}/orders", a.listOrders)
	r.Post("/orders", a.createOrder)
	r.Put("/orders/{id}", a.updateOrder)
	r.Post("/orders/{id}/pay", a.payOrder)
	r.NotFound(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusNotFound, errorBody{"not found"})
	})
	r.MethodNotAllowed(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusMethodNotAllowed, errorBody{"method not allowed"})
	})
	return r
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

// fail memetakan error domain ke status HTTP; kesalahan tak terduga dicatat lewat logger per request.
func fail(w http.ResponseWriter, r *http.Request, err error) {
	var ve *domain.ValidationError
	switch {
	case errors.As(err, &ve):
		writeJSON(w, http.StatusBadRequest, errorBody{ve.Msg})
	case errors.Is(err, domain.ErrNotFound):
		writeJSON(w, http.StatusNotFound, errorBody{"not found"})
	default:
		if l := loghttp.FromRequest(r); l != nil {
			l.WithError(err).Error("request failed")
		}
		writeJSON(w, http.StatusInternalServerError, errorBody{"internal error"})
	}
}

func readBody(r *http.Request, v any) error {
	b, err := io.ReadAll(http.MaxBytesReader(nil, r.Body, 1<<20))
	if err != nil {
		return &domain.ValidationError{Msg: domain.MsgInvalidBody}
	}
	if err := json.Unmarshal(b, v); err != nil {
		return &domain.ValidationError{Msg: domain.MsgInvalidBody}
	}
	return nil
}

func (a *API) healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (a *API) benchJSON(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, domain.NewBenchPayload())
}

func (a *API) benchEcho(w http.ResponseWriter, r *http.Request) {
	var in domain.EchoRequest
	if err := readBody(r, &in); err != nil {
		fail(w, r, err)
		return
	}
	if err := in.Validate(); err != nil {
		fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, in)
}

func (a *API) getUser(w http.ResponseWriter, r *http.Request) {
	id, err := domain.ParseID(chi.URLParam(r, "id"))
	if err != nil {
		fail(w, r, err)
		return
	}
	if r.URL.Query().Get("include") == "orders" {
		u, err := a.Users.GetUserWithOrders(r.Context(), id)
		if err != nil {
			fail(w, r, err)
			return
		}
		writeJSON(w, http.StatusOK, u)
		return
	}
	u, err := a.Users.GetUser(r.Context(), id)
	if err != nil {
		fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, u)
}

func (a *API) listOrders(w http.ResponseWriter, r *http.Request) {
	id, err := domain.ParseID(chi.URLParam(r, "id"))
	if err != nil {
		fail(w, r, err)
		return
	}
	limit, err := domain.ParseLimit(r.URL.Query().Get("limit"))
	if err != nil {
		fail(w, r, err)
		return
	}
	orders, err := a.Users.ListOrders(r.Context(), id, limit)
	if err != nil {
		fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, orders)
}

func (a *API) createOrder(w http.ResponseWriter, r *http.Request) {
	var in domain.CreateOrderInput
	if err := readBody(r, &in); err != nil {
		fail(w, r, err)
		return
	}
	if err := in.Normalize(); err != nil {
		fail(w, r, err)
		return
	}
	o, err := a.Orders.CreateOrder(r.Context(), in)
	if err != nil {
		fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, o)
}

func (a *API) updateOrder(w http.ResponseWriter, r *http.Request) {
	id, err := domain.ParseID(chi.URLParam(r, "id"))
	if err != nil {
		fail(w, r, err)
		return
	}
	var in domain.UpdateOrderInput
	if err := readBody(r, &in); err != nil {
		fail(w, r, err)
		return
	}
	if err := in.Validate(); err != nil {
		fail(w, r, err)
		return
	}
	o, err := a.Orders.UpdateOrderStatus(r.Context(), id, in.Status)
	if err != nil {
		fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, o)
}

func (a *API) payOrder(w http.ResponseWriter, r *http.Request) {
	id, err := domain.ParseID(chi.URLParam(r, "id"))
	if err != nil {
		fail(w, r, err)
		return
	}
	res, err := a.Orders.PayOrder(r.Context(), id)
	if err != nil {
		fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, res)
}
