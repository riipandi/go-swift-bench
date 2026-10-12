// Package store adalah repositori GORM. Pemetaan tabel/kolom eksplisit; tidak ada AutoMigrate dan tidak ada SQL mentah.
package store

import (
	"cmp"
	"context"
	"errors"
	"slices"
	"time"

	"benchapp/internal/domain"

	"gorm.io/gorm"
)

type userRecord struct {
	ID        int64         `gorm:"column:id;primaryKey"`
	Name      string        `gorm:"column:name"`
	Email     string        `gorm:"column:email"`
	CreatedAt time.Time     `gorm:"column:created_at"`
	Orders    []orderRecord `gorm:"foreignKey:UserID;references:ID"`
}

func (userRecord) TableName() string { return "users" }

type orderRecord struct {
	ID         int64     `gorm:"column:id;primaryKey"`
	UserID     int64     `gorm:"column:user_id"`
	Status     string    `gorm:"column:status"`
	TotalCents int       `gorm:"column:total_cents"`
	Note       string    `gorm:"column:note"`
	CreatedAt  time.Time `gorm:"column:created_at"`
	UpdatedAt  time.Time `gorm:"column:updated_at"`
}

func (orderRecord) TableName() string { return "orders" }

type paymentRecord struct {
	ID          int64     `gorm:"column:id;primaryKey"`
	OrderID     int64     `gorm:"column:order_id"`
	AmountCents int       `gorm:"column:amount_cents"`
	CreatedAt   time.Time `gorm:"column:created_at"`
}

func (paymentRecord) TableName() string { return "payments" }

func (r userRecord) toDomain() domain.User {
	return domain.User{ID: r.ID, Name: r.Name, Email: r.Email, CreatedAt: r.CreatedAt.UTC()}
}

func (r orderRecord) toDomain() domain.Order {
	return domain.Order{ID: r.ID, UserID: r.UserID, Status: r.Status, TotalCents: r.TotalCents,
		Note: r.Note, CreatedAt: r.CreatedAt.UTC(), UpdatedAt: r.UpdatedAt.UTC()}
}

func ordersToDomain(rs []orderRecord) []domain.Order {
	out := make([]domain.Order, len(rs))
	for i := range rs {
		out[i] = rs[i].toDomain()
	}
	return out
}

func mapErr(err error) error {
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return domain.ErrNotFound
	}
	return err
}

// UserRepository dan OrderRepository adalah antarmuka kecil; handler memakainya sehingga test bisa memakai repositori palsu.
type UserRepository interface {
	GetUser(ctx context.Context, id int64) (domain.User, error)
	ListOrders(ctx context.Context, userID int64, limit int) ([]domain.Order, error)
	GetUserWithOrders(ctx context.Context, id int64) (domain.UserWithOrders, error)
}

type OrderRepository interface {
	CreateOrder(ctx context.Context, in domain.CreateOrderInput) (domain.Order, error)
	UpdateOrderStatus(ctx context.Context, id int64, status string) (domain.Order, error)
	PayOrder(ctx context.Context, id int64) (domain.PayResult, error)
}

// Repo adalah implementasi GORM dari kedua antarmuka.
type Repo struct{ db *gorm.DB }

func New(db *gorm.DB) *Repo { return &Repo{db: db} }

func now() time.Time { return time.Now().UTC() }

func (r *Repo) GetUser(ctx context.Context, id int64) (domain.User, error) {
	var rec userRecord
	if err := r.db.WithContext(ctx).First(&rec, id).Error; err != nil {
		return domain.User{}, mapErr(err)
	}
	return rec.toDomain(), nil
}

func (r *Repo) ListOrders(ctx context.Context, userID int64, limit int) ([]domain.Order, error) {
	var recs []orderRecord
	err := r.db.WithContext(ctx).
		Where("user_id = ?", userID).
		Order("created_at DESC, id DESC").
		Limit(limit).
		Find(&recs).Error
	if err != nil {
		return nil, err
	}
	return ordersToDomain(recs), nil
}

func (r *Repo) GetUserWithOrders(ctx context.Context, id int64) (domain.UserWithOrders, error) {
	var rec userRecord
	err := r.db.WithContext(ctx).
		Preload("Orders").
		First(&rec, id).Error
	if err != nil {
		return domain.UserWithOrders{}, mapErr(err)
	}
	// Preload tidak diurutkan; urutan (created_at DESC, id DESC) diterapkan di memori (Fluent `with` tidak mendukung ORDER BY).
	orders := ordersToDomain(rec.Orders)
	slices.SortFunc(orders, func(a, b domain.Order) int {
		if c := b.CreatedAt.Compare(a.CreatedAt); c != 0 {
			return c
		}
		return cmp.Compare(b.ID, a.ID)
	})
	return domain.UserWithOrders{User: rec.toDomain(), Orders: orders}, nil
}

func (r *Repo) CreateOrder(ctx context.Context, in domain.CreateOrderInput) (domain.Order, error) {
	t := now()
	rec := orderRecord{UserID: in.UserID, Status: in.Status, TotalCents: in.TotalCents, Note: in.Note, CreatedAt: t, UpdatedAt: t}
	if err := r.db.WithContext(ctx).Create(&rec).Error; err != nil {
		return domain.Order{}, err
	}
	return rec.toDomain(), nil
}

func (r *Repo) UpdateOrderStatus(ctx context.Context, id int64, status string) (domain.Order, error) {
	db := r.db.WithContext(ctx)
	var rec orderRecord
	if err := db.First(&rec, id).Error; err != nil {
		return domain.Order{}, mapErr(err)
	}
	t := now()
	if err := db.Model(&rec).Updates(map[string]any{"status": status, "updated_at": t}).Error; err != nil {
		return domain.Order{}, err
	}
	rec.Status, rec.UpdatedAt = status, t
	return rec.toDomain(), nil
}

func (r *Repo) PayOrder(ctx context.Context, id int64) (domain.PayResult, error) {
	var out domain.PayResult
	err := r.db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var rec orderRecord
		if err := tx.First(&rec, id).Error; err != nil {
			return mapErr(err)
		}
		t := now()
		if err := tx.Model(&rec).Updates(map[string]any{"status": domain.StatusPaid, "updated_at": t}).Error; err != nil {
			return err
		}
		rec.Status, rec.UpdatedAt = domain.StatusPaid, t
		pay := paymentRecord{OrderID: rec.ID, AmountCents: rec.TotalCents, CreatedAt: t}
		if err := tx.Create(&pay).Error; err != nil {
			return err
		}
		out = domain.PayResult{
			Order:   rec.toDomain(),
			Payment: domain.Payment{ID: pay.ID, OrderID: pay.OrderID, AmountCents: pay.AmountCents, CreatedAt: pay.CreatedAt},
		}
		return nil
	})
	return out, err
}
